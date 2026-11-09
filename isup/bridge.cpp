// Argus ISUP 5.0 bridge.
//
// A Hikvision camera or recorder with ISUP ("Platform Access") enabled dials
// out to this service by itself, so it can sit behind any NAT with no port
// forwarding on its side. The bridge accepts the registration, checks the
// device's encryption key, and when the backend asks for a channel it pulls
// the live video (MPEG-PS) and republishes it to go2rtc untouched:
//
//   device --ISUP 17660 tcp/udp--> bridge <--video 17661 tcp-- device
//                                    |  ffmpeg -c copy
//                                    v
//                    rtsp://go2rtc:8554/<stream name>
//
// The backend drives everything through a small HTTP API on API_PORT, reached
// only inside the Docker network:
//   GET /health
//   GET /devices   registered devices, their channels and open streams (JSON)
//   PUT /keys      one "<deviceID> <key>" per line: who may register
//   PUT /want      one "<deviceID> <channel> <0|1> <stream>" per line:
//                  which streams to keep open (0 main, 1 sub) and where to
//                  publish each one in go2rtc
// With API_TOKEN set, every call needs the "X-Bridge-Token" header.
//
// Environment:
//   PUBLIC_IP        address the devices reach this server at (required)
//   CMS_PORT         registration port, tcp+udp (17660)
//   STREAM_PORT      video port, tcp (17661)
//   API_PORT         internal API (8091)
//   API_TOKEN        optional shared secret with the backend
//   RTSP_BASE        where to publish (rtsp://go2rtc:8554)
//   SDK_LIB          folder with the Hikvision ISUP SDK libraries
//   ACCESS_SECURITY  SDK access mode: 0 compatible (default), 2 secure only
//
// The SDK calls follow Hikvision's ISUP SDK samples, as used by the Vizora
// project's pilot bridge, which proved this sequence on real devices.
#include <arpa/inet.h>
#include <netinet/in.h>
#include <signal.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include "HCISUPCMS.h"
#include "HCISUPStream.h"

// --- small helpers --------------------------------------------------------------

static std::string env(const char* name, const char* fallback) {
    const char* v = getenv(name);
    return (v && *v) ? v : fallback;
}

static double now_s() {
    using namespace std::chrono;
    return duration<double>(system_clock::now().time_since_epoch()).count();
}

#define LOG(fmt, ...)                                                              \
    do {                                                                           \
        time_t t_ = time(nullptr);                                                 \
        char b_[16];                                                               \
        strftime(b_, sizeof b_, "%H:%M:%S", localtime(&t_));                       \
        fprintf(stderr, "%s " fmt "\n", b_, ##__VA_ARGS__);                        \
        fflush(stderr);                                                            \
    } while (0)

// Device IDs come from the network and end up in stream names and a shell
// command line, so only a safe alphabet is accepted.
static bool safe_name(const std::string& s, size_t max = 64) {
    if (s.empty() || s.size() > max) return false;
    for (char c : s)
        if (!(isalnum((unsigned char)c) || c == '_' || c == '-')) return false;
    return true;
}

static bool safe_key(const std::string& k) {
    if (k.size() < 8 || k.size() > 32) return false;
    for (char c : k)
        if (!isalnum((unsigned char)c)) return false;
    return true;
}

// SDK char arrays are not always NUL-terminated.
static std::string field(const void* p, size_t n) {
    const char* c = static_cast<const char*>(p);
    return std::string(c, strnlen(c, n));
}

// Length of the valid UTF-8 sequence at s[i], or 0 if the bytes there are not one.
static size_t utf8_len(const std::string& s, size_t i) {
    unsigned char c = (unsigned char)s[i];
    size_t n = c >= 0xf0 && c <= 0xf4 ? 4 : c >= 0xe0 && c <= 0xef ? 3 : c >= 0xc2 && c <= 0xdf ? 2 : 0;
    if (n == 0 || i + n > s.size()) return 0;
    for (size_t k = 1; k < n; k++)
        if (((unsigned char)s[i + k] & 0xc0) != 0x80) return 0;
    return n;
}

// Text from a device as a JSON string. A recorder's channel names are often
// Cyrillic, so valid UTF-8 passes through whole; control characters and stray
// bytes (some firmware uses legacy code pages) are replaced, so the JSON the
// backend reads is always valid.
static std::string json(const std::string& s) {
    std::string o = "\"";
    for (size_t i = 0; i < s.size();) {
        unsigned char c = (unsigned char)s[i];
        size_t n = 0;
        if (c == '"' || c == '\\') {
            o += '\\';
            o += (char)c;
            i++;
        } else if (c < 0x20 || c == 0x7f) {
            char b[8];
            snprintf(b, sizeof b, "\\u%04x", c);
            o += b;
            i++;
        } else if (c < 0x80) {
            o += (char)c;
            i++;
        } else if ((n = utf8_len(s, i)) > 0) {
            o.append(s, i, n);
            i += n;
        } else {
            o += "\\ufffd";
            i++;
        }
    }
    return o + "\"";
}

static std::string printable(const std::string& s) {
    std::string o;
    for (unsigned char c : s.substr(0, 64)) o += (c >= 0x20 && c < 0x7f) ? (char)c : '?';
    return o.empty() ? "?" : o;
}

// --- configuration -------------------------------------------------------------------

static std::string g_public_ip, g_rtsp_base, g_api_token;
static int g_cms_port = 17660, g_stream_port = 17661, g_api_port = 8091;

// --- one open stream: SDK callback -> queue -> ffmpeg ---------------------------
//
// The SDK's data callback must never block: if it waits on a full pipe, the
// device's socket stops being read and frames break. So data goes into a
// bounded queue and a separate thread feeds ffmpeg; when the queue is full
// the oldest data is dropped and ffmpeg resyncs on the next PS pack.

struct Stream {
    std::string dev, target;  // device ID, go2rtc stream name
    int channel = 0, type = 0;  // type: 0 main, 1 sub
    LONG user = -1;              // the device's CMS login
    LONG session = -1;           // CMS stream session
    std::atomic<LONG> link{-1};  // stream-server link (set by the new-link callback)
    double asked_at = 0;
    std::atomic<double> last_data{0};
    std::atomic<long long> bytes{0};
    std::atomic<bool> stop{false};

    FILE* ff = nullptr;
    std::thread writer;
    std::mutex mu;
    std::condition_variable cv;
    std::deque<std::string> queue;
    size_t queued = 0;

    std::string key() const { return dev + " " + std::to_string(channel) + " " + std::to_string(type); }

    bool start_ffmpeg() {
        // No "-fflags nobuffer": it swallows the first keyframe. ffmpeg runs
        // without the SDK's library path, whose old OpenSSL/zlib break it.
        std::string cmd =
            "exec env -u LD_LIBRARY_PATH ffmpeg -hide_banner -loglevel warning -nostdin"
            " -fflags +genpts+discardcorrupt -probesize 1000000 -analyzeduration 1000000"
            " -f mpeg -i pipe:0 -map 0:v:0 -c:v copy -an"
            " -f rtsp -rtsp_transport tcp " + g_rtsp_base + "/" + target;
        ff = popen(cmd.c_str(), "w");
        if (!ff) return false;
        writer = std::thread([this] { feed(); });
        return true;
    }

    void push(const void* data, size_t n) {
        std::lock_guard<std::mutex> lk(mu);
        const size_t cap = 8u << 20;
        while (queued + n > cap && !queue.empty()) {
            queued -= queue.front().size();
            queue.pop_front();
        }
        queue.emplace_back(static_cast<const char*>(data), n);
        queued += n;
        cv.notify_one();
    }

    void feed() {
        while (!stop) {
            std::string chunk;
            {
                std::unique_lock<std::mutex> lk(mu);
                cv.wait_for(lk, std::chrono::milliseconds(500), [this] { return !queue.empty() || stop; });
                if (queue.empty()) continue;
                chunk.swap(queue.front());
                queue.pop_front();
                queued -= chunk.size();
            }
            if (fwrite(chunk.data(), 1, chunk.size(), ff) != chunk.size()) {
                LOG("[%s] ffmpeg exited", target.c_str());
                stop = true;
                break;
            }
            fflush(ff);
        }
    }

    void close() {
        stop = true;
        cv.notify_all();
        if (writer.joinable()) writer.join();
        if (ff) {
            pclose(ff);
            ff = nullptr;
        }
    }
};

// --- shared state (all under g_mu) ----------------------------------------------------

struct Channel {
    int id = 0;
    std::string name;
    bool online = true;
};

struct Device {
    LONG user = -1;
    std::string serial, ip, firmware, protocol, model, name;
    double since = 0;
    std::string info = "pending";  // pending | ok | failed
    int dev_type = 0, analog = 0, total = 0, start = 1;
    std::vector<Channel> channels;  // a recorder's IP channels
};

// A passed key check (ENUM_DEV_AUTH) is a one-time ticket for the "device
// on" event that follows on the same connection. Without it, compatible
// mode would also let an old keyless protocol register any device ID.
struct Ticket {
    double at = 0;
    LONG auth_user = -1;
    LONG on_user = -1;
    bool used = false;
};

struct Want {
    std::string dev, target;
    int channel, type;
};

static std::mutex g_mu;
static std::condition_variable g_wake;
static std::map<std::string, std::string> g_keys;  // device ID -> key
static bool g_keys_set = false;
static std::map<std::string, Ticket> g_tickets;
static std::map<std::string, Device> g_devices;
static std::map<std::string, std::pair<std::string, double>> g_rejected;  // id -> (reason, when)
static std::map<std::string, Want> g_want;  // stream key -> what to open
static std::map<std::string, std::shared_ptr<Stream>> g_streams;  // stream key -> open stream
static std::map<LONG, std::shared_ptr<Stream>> g_by_session;
static std::set<std::string> g_opening;
static std::map<std::string, std::pair<int, double>> g_backoff;  // key -> (failures, next try)
// Stopped streams stay alive for a while: the SDK holds a raw pointer to
// them, and a late callback must not write into freed memory.
static std::vector<std::pair<double, std::shared_ptr<Stream>>> g_retired;

static void reject_locked(const std::string& dev, const std::string& reason) {
    if (!safe_name(dev)) return;
    if (g_rejected.size() > 300) g_rejected.clear();
    g_rejected[dev] = {reason, now_s()};
}

// --- video ----------------------------------------------------------------------------

static void CALLBACK on_data(LONG, NET_EHOME_PREVIEW_CB_MSG* msg, void* user) {
    auto* s = static_cast<Stream*>(user);
    if (!msg || !s || s->stop) return;
    if (msg->byDataType == 1) return;  // 40-byte Hikvision header, not video
    if (s->bytes == 0) LOG("[%s] first video after %.2fs", s->target.c_str(), now_s() - s->asked_at);
    s->last_data = now_s();
    s->bytes += msg->dwDataLen;
    s->push(msg->pRecvdata, msg->dwDataLen);
}

static BOOL CALLBACK on_new_link(LONG link, NET_EHOME_NEWLINK_CB_MSG* msg, void*) {
    std::shared_ptr<Stream> s;
    {
        std::lock_guard<std::mutex> lk(g_mu);
        auto it = g_by_session.find(msg->iSessionID);
        if (it != g_by_session.end()) s = it->second;
    }
    if (!s) return FALSE;
    s->link = link;
    NET_EHOME_PREVIEW_DATA_CB_PARAM cb{};
    cb.fnPreviewDataCB = on_data;
    cb.pUserData = s.get();
    cb.byStreamFormat = 0;  // PS
    if (!NET_ESTREAM_SetPreviewDataCB(link, &cb)) {
        LOG("[%s] SetPreviewDataCB failed: %u", s->target.c_str(), NET_ESTREAM_GetLastError());
        return FALSE;
    }
    if (s->stop) {  // stopped while the link was coming up
        NET_ESTREAM_StopPreview(link);
        return FALSE;
    }
    return TRUE;
}

static void stop_stream(const std::shared_ptr<Stream>& s) {
    if (s->link >= 0) NET_ESTREAM_StopPreview(s->link);
    if (s->session >= 0) NET_ECMS_StopGetRealStream(s->user, s->session);
    {
        std::lock_guard<std::mutex> lk(g_mu);
        g_by_session.erase(s->session);
        g_retired.emplace_back(now_s(), s);
    }
    s->close();
}

// Opening is slow (StartPushRealStream returns after ~5 s while video already
// flows), so each stream opens on its own thread.
static void open_stream(Want w, LONG user) {
    auto s = std::make_shared<Stream>();
    s->dev = w.dev;
    s->target = w.target;
    s->channel = w.channel;
    s->type = w.type;
    s->user = user;
    s->asked_at = now_s();
    const std::string key = s->key();
    auto finish = [&](bool ok) {
        std::lock_guard<std::mutex> lk(g_mu);
        g_opening.erase(key);
        if (!ok) {
            auto& b = g_backoff[key];
            b.first++;
            b.second = now_s() + std::min(60, 3 << std::min(b.first, 5));
        }
    };

    if (!s->start_ffmpeg()) {
        LOG("[%s] ffmpeg did not start", s->target.c_str());
        return finish(false);
    }
    NET_EHOME_PREVIEWINFO_IN_V11 in{};
    in.iChannel = w.channel;
    in.dwStreamType = w.type;
    in.dwLinkMode = 0;  // TCP
    snprintf(in.struStreamSever.szIP, sizeof in.struStreamSever.szIP, "%s", g_public_ip.c_str());
    in.struStreamSever.wPort = (WORD)g_stream_port;
    NET_EHOME_PREVIEWINFO_OUT out{};
    if (!NET_ECMS_StartGetRealStreamV11(user, &in, &out)) {
        LOG("[%s] StartGetRealStreamV11 failed: %u", s->target.c_str(), NET_ECMS_GetLastError());
        s->close();
        return finish(false);
    }
    s->session = out.lSessionID;
    {
        std::lock_guard<std::mutex> lk(g_mu);
        g_by_session[out.lSessionID] = s;
        g_streams[key] = s;
    }
    NET_EHOME_PUSHSTREAM_IN pin{};
    pin.dwSize = sizeof pin;
    pin.lSessionID = out.lSessionID;
    NET_EHOME_PUSHSTREAM_OUT pout{};
    pout.dwSize = sizeof pout;
    if (!NET_ECMS_StartPushRealStream(user, &pin, &pout))
        LOG("[%s] StartPushRealStream failed: %u", s->target.c_str(), NET_ECMS_GetLastError());
    // Ask for a keyframe now, so the picture does not wait for the next GOP.
    NET_EHOME_MAKE_I_FRAME iframe{};
    iframe.iChannel = w.channel;
    iframe.dwStreamType = w.type;
    NET_ECMS_MakeIFrame(user, &iframe);
    LOG("[%s] requested %s ch%d %s", s->target.c_str(), printable(w.dev).c_str(), w.channel, w.type ? "sub" : "main");
    finish(true);
}

// Keeps the open streams equal to what the backend wants, restarting any
// that stopped sending video.
static void supervisor() {
    while (true) {
        std::vector<std::shared_ptr<Stream>> to_stop;
        std::vector<std::pair<Want, LONG>> to_open;
        {
            std::unique_lock<std::mutex> lk(g_mu);
            g_wake.wait_for(lk, std::chrono::seconds(2));
            const double now = now_s();
            for (auto it = g_streams.begin(); it != g_streams.end();) {
                auto& s = it->second;
                auto w = g_want.find(it->first);
                auto d = g_devices.find(s->dev);
                bool gone = w == g_want.end() || w->second.target != s->target ||
                            d == g_devices.end() || d->second.user != s->user;
                bool silent = now - std::max(s->asked_at, s->last_data.load()) > 15;
                if (gone || silent || s->stop) {
                    if (!gone) {
                        LOG("[%s] no video, will retry", s->target.c_str());
                        auto& b = g_backoff[it->first];
                        b.first++;
                        b.second = now + std::min(60, 3 << std::min(b.first, 5));
                    }
                    to_stop.push_back(s);
                    it = g_streams.erase(it);
                } else {
                    if (s->bytes > 0) g_backoff.erase(it->first);
                    ++it;
                }
            }
            for (auto& [key, w] : g_want) {
                if (g_streams.count(key) || g_opening.count(key)) continue;
                auto d = g_devices.find(w.dev);
                if (d == g_devices.end()) continue;
                auto b = g_backoff.find(key);
                if (b != g_backoff.end() && b->second.second > now) continue;
                g_opening.insert(key);
                to_open.emplace_back(w, d->second.user);
            }
            for (auto it = g_retired.begin(); it != g_retired.end();)
                it = now - it->first > 30 ? g_retired.erase(it) : std::next(it);
        }
        for (auto& s : to_stop) stop_stream(s);
        for (auto& [w, user] : to_open) std::thread(open_stream, w, user).detach();
    }
}

// --- device details: a recorder's channels ---------------------------------------------

static std::string isapi_get(LONG user, const std::string& url) {
    std::string req = "GET " + url;
    std::vector<char> out(512 * 1024);
    NET_EHOME_PTXML_PARAM p{};
    p.pRequestUrl = (void*)req.c_str();
    p.dwRequestUrlLen = (DWORD)req.size();
    p.pOutBuffer = out.data();
    p.dwOutSize = (DWORD)out.size();
    p.dwRecvTimeOut = 8000;
    if (!NET_ECMS_ISAPIPassThrough(user, &p)) return "";
    return std::string(out.data(), std::min<size_t>(p.dwReturnedXMLLen, out.size()));
}

// Text of the first <name>…</name> inside [from, to).
static std::string tag(const std::string& x, const std::string& name, size_t from, size_t to) {
    size_t a = x.find("<" + name + ">", from);
    if (a == std::string::npos || a >= to) return "";
    a += name.size() + 2;
    size_t b = x.find("</" + name + ">", a);
    if (b == std::string::npos || b > to) return "";
    return x.substr(a, b - a);
}

// [start, end) of each exact <name> element (not <nameSomething>).
static std::vector<std::pair<size_t, size_t>> blocks(const std::string& x, const std::string& name) {
    std::vector<std::pair<size_t, size_t>> out;
    for (size_t p = 0; (p = x.find("<" + name, p)) != std::string::npos;) {
        char next = p + 1 + name.size() < x.size() ? x[p + 1 + name.size()] : 0;
        if (next != '>' && next != ' ') {
            p += name.size();
            continue;
        }
        size_t e = x.find("</" + name + ">", p);
        if (e == std::string::npos) break;
        out.emplace_back(p, e);
        p = e;
    }
    return out;
}

static void read_details(std::string dev, LONG user) {
    std::this_thread::sleep_for(std::chrono::milliseconds(800));  // let the session key settle
    Device got;
    bool ok = false;
    NET_EHOME_DEVICE_INFO di{};
    di.dwSize = sizeof di;
    NET_EHOME_CONFIG cfg{};
    cfg.pOutBuf = &di;
    cfg.dwOutSize = sizeof di;
    if (NET_ECMS_GetDevConfig(user, NET_EHOME_GET_DEVICE_INFO, &cfg, sizeof cfg)) {
        ok = true;
        got.dev_type = (int)di.dwDevType;
        got.analog = (int)di.dwChannelNumber;
        got.total = (int)di.dwChannelAmount;
        got.start = di.dwStartChannel ? (int)di.dwStartChannel : 1;
    }
    std::string about = isapi_get(user, "/ISAPI/System/deviceInfo");
    if (!about.empty()) {
        got.model = tag(about, "model", 0, about.size());
        got.name = tag(about, "deviceName", 0, about.size());
        ok = true;
    }
    std::string list = isapi_get(user, "/ISAPI/ContentMgmt/InputProxy/channels");
    if (!list.empty()) {
        std::string status = isapi_get(user, "/ISAPI/ContentMgmt/InputProxy/channels/status");
        std::map<int, bool> online;
        for (auto [a, b] : blocks(status, "InputProxyChannelStatus"))
            online[atoi(tag(status, "id", a, b).c_str())] = tag(status, "online", a, b) == "true";
        for (auto [a, b] : blocks(list, "InputProxyChannel")) {
            Channel c;
            c.id = atoi(tag(list, "id", a, b).c_str());
            if (c.id <= 0) continue;
            c.name = tag(list, "name", a, b);
            auto o = online.find(c.id);
            c.online = o == online.end() || o->second;
            got.channels.push_back(c);
        }
        ok = true;
    }
    std::lock_guard<std::mutex> lk(g_mu);
    auto it = g_devices.find(dev);
    if (it == g_devices.end() || it->second.user != user) return;  // gone meanwhile
    auto& d = it->second;
    d.info = ok ? "ok" : "failed";
    d.dev_type = got.dev_type;
    d.analog = got.analog;
    d.total = got.total;
    d.start = got.start;
    d.channels = got.channels;
    d.model = got.model;
    d.name = got.name;
    LOG("[%s] %d channel(s), %zu IP channel(s)", printable(dev).c_str(), d.total, d.channels.size());
}

// --- registration ---------------------------------------------------------------------

static std::string id_from(const void* out, DWORD len) {
    if (!out || len < offsetof(NET_EHOME_DEV_REG_INFO, byDeviceID) + MAX_DEVICE_ID_LEN) return "";
    auto* r = static_cast<const NET_EHOME_DEV_REG_INFO*>(out);
    return field(r->byDeviceID, sizeof r->byDeviceID);
}

static BOOL CALLBACK on_register(LONG user, DWORD type, void* out, DWORD out_len, void* in, DWORD in_len, void*) {
    switch (type) {
    case ENUM_DEV_AUTH: {  // ISUP 5.0: the SDK checks the device against the key we return
        const std::string dev = id_from(out, out_len);
        std::string key;
        {
            std::lock_guard<std::mutex> lk(g_mu);
            auto k = g_keys.find(dev);
            if (k == g_keys.end()) {
                reject_locked(dev, "unknown");
            } else {
                key = k->second;
                g_tickets[dev] = {now_s(), user, -1, false};
            }
            for (auto it = g_tickets.begin(); it != g_tickets.end();)
                it = now_s() - it->second.at > 600 && !g_devices.count(it->first) ? g_tickets.erase(it) : std::next(it);
        }
        if (key.empty()) {
            LOG("[cms] rejected %s: no such device ID in Argus", printable(dev).c_str());
            return FALSE;
        }
        if (!in || in_len == 0) return FALSE;
        memset(in, 0, in_len);
        memcpy(in, key.data(), std::min<size_t>(key.size(), in_len));
        return TRUE;
    }
    case ENUM_DEV_SESSIONKEY: {
        if (!out) return FALSE;
        auto* info = static_cast<NET_EHOME_DEV_REG_INFO_V12*>(out);
        NET_EHOME_DEV_SESSIONKEY sk{};
        memcpy(sk.sDeviceID, info->struRegInfo.byDeviceID, MAX_DEVICE_ID_LEN);
        memcpy(sk.sSessionKey, info->struRegInfo.bySessionKey, MAX_MASTER_KEY_LEN);
        NET_ECMS_SetDeviceSessionKey(&sk);
        return TRUE;
    }
    case ENUM_DEV_DAS_REQ:  // the device asks where to register: here
        if (!in || in_len == 0) return FALSE;
        snprintf((char*)in, in_len,
                 "{\"Type\":\"DAS\",\"DasInfo\":{\"Address\":\"%s\",\"Domain\":\"\",\"ServerID\":\"das_%s_%d\","
                 "\"Port\":%d,\"UdpPort\":%d}}",
                 g_public_ip.c_str(), g_public_ip.c_str(), g_cms_port, g_cms_port, g_cms_port);
        return TRUE;
    case ENUM_DEV_ON: {
        if (!out) return FALSE;
        auto* info = static_cast<NET_EHOME_DEV_REG_INFO_V12*>(out);
        auto& r = info->struRegInfo;
        const std::string dev = field(r.byDeviceID, sizeof r.byDeviceID);
        Device d;
        d.user = user;
        d.serial = field(r.sDeviceSerial, sizeof r.sDeviceSerial);
        d.ip = field(r.struDevAdd.szIP, sizeof r.struDevAdd.szIP);
        d.firmware = field(r.byFirmwareVersion, sizeof r.byFirmwareVersion);
        d.protocol = field(r.byDevProtocolVersion, sizeof r.byDevProtocolVersion);
        d.since = now_s();
        LONG previous = -1;
        {
            std::lock_guard<std::mutex> lk(g_mu);
            auto t = g_tickets.find(dev);
            bool ok = safe_name(dev) && t != g_tickets.end() && now_s() - t->second.at < 120 &&
                      (t->second.used ? t->second.on_user == user
                                      : t->second.auth_user < 0 || t->second.auth_user == user);
            if (!ok) {
                reject_locked(dev, safe_name(dev) ? "no_key_check" : "bad_id");
                LOG("[cms] rejected %s: registered without the ISUP 5.0 key check", printable(dev).c_str());
                return FALSE;
            }
            t->second.used = true;
            t->second.on_user = user;
            auto old = g_devices.find(dev);
            if (old != g_devices.end() && old->second.user != user) previous = old->second.user;
            g_rejected.erase(dev);
            g_devices[dev] = d;
            for (auto it = g_backoff.begin(); it != g_backoff.end();)
                it = it->first.rfind(dev + " ", 0) == 0 ? g_backoff.erase(it) : std::next(it);
        }
        if (previous >= 0) NET_ECMS_ForceLogout(previous);  // same ID connected twice: newest wins
        if (in) {
            auto* srv = static_cast<NET_EHOME_SERVER_INFO_V50*>(in);
            srv->dwKeepAliveSec = 15;
            srv->dwTimeOutCount = 4;
        }
        LOG("[cms] connected %s serial=%s ip=%s fw=%s", dev.c_str(), printable(d.serial).c_str(),
            printable(d.ip).c_str(), printable(d.firmware).c_str());
        g_wake.notify_all();
        std::thread(read_details, dev, user).detach();
        return TRUE;
    }
    case ENUM_DEV_OFF: {
        {
            std::lock_guard<std::mutex> lk(g_mu);
            for (auto it = g_devices.begin(); it != g_devices.end(); ++it)
                if (it->second.user == user) {
                    LOG("[cms] disconnected %s", it->first.c_str());
                    g_devices.erase(it);
                    break;
                }
        }
        NET_ECMS_ForceLogout(user);
        g_wake.notify_all();
        return TRUE;
    }
    case ENUM_DEV_DAS_EHOMEKEY_ERROR: {
        const std::string dev = id_from(out, out_len);
        {
            std::lock_guard<std::mutex> lk(g_mu);
            reject_locked(dev, "wrong_key");
        }
        LOG("[cms] %s: the encryption key on the device does not match", printable(dev).c_str());
        return TRUE;
    }
    default:
        return TRUE;
    }
}

static void CALLBACK on_stream_exception(DWORD type, LONG, LONG handle, void*) {
    LOG("[stream] exception 0x%x on handle %d", type, handle);
}

// --- internal HTTP API -----------------------------------------------------------------

static std::string devices_json() {
    std::lock_guard<std::mutex> lk(g_mu);
    const double now = now_s();
    std::ostringstream o;
    o << "{\"keys_set\":" << (g_keys_set ? "true" : "false") << ",\"devices\":[";
    bool first = true;
    for (auto& [id, d] : g_devices) {
        o << (first ? "" : ",") << "{\"id\":" << json(id) << ",\"serial\":" << json(d.serial)
          << ",\"ip\":" << json(d.ip) << ",\"firmware\":" << json(d.firmware)
          << ",\"model\":" << json(d.model) << ",\"name\":" << json(d.name)
          << ",\"since\":" << (long long)d.since << ",\"info\":" << json(d.info)
          << ",\"dev_type\":" << d.dev_type << ",\"analog\":" << d.analog << ",\"total\":" << d.total
          << ",\"start\":" << d.start << ",\"channels\":[";
        for (size_t i = 0; i < d.channels.size(); i++)
            o << (i ? "," : "") << "{\"id\":" << d.channels[i].id << ",\"name\":" << json(d.channels[i].name)
              << ",\"online\":" << (d.channels[i].online ? "true" : "false") << "}";
        o << "]}";
        first = false;
    }
    o << "],\"streams\":[";
    first = true;
    for (auto& [key, s] : g_streams) {
        double last = s->last_data.load();
        o << (first ? "" : ",") << "{\"target\":" << json(s->target) << ",\"bytes\":" << s->bytes.load()
          << ",\"idle\":" << (last > 0 ? (int)(now - last) : -1) << "}";
        first = false;
    }
    o << "],\"rejected\":[";
    first = true;
    for (auto& [id, r] : g_rejected) {
        o << (first ? "" : ",") << "{\"id\":" << json(id) << ",\"reason\":" << json(r.first)
          << ",\"at\":" << (long long)r.second << "}";
        first = false;
    }
    o << "]}";
    return o.str();
}

static std::string apply_keys(const std::string& body) {
    std::map<std::string, std::string> keys;
    std::istringstream in(body);
    for (std::string line; std::getline(in, line);) {
        std::istringstream l(line);
        std::string id, key;
        if (l >> id >> key && safe_name(id) && safe_key(key)) keys[id] = key;
    }
    std::vector<LONG> drop;
    {
        std::lock_guard<std::mutex> lk(g_mu);
        // A device whose key was removed or changed is logged out: it must not
        // keep working on a key that no longer applies.
        for (auto& [id, d] : g_devices) {
            auto now_key = keys.find(id);
            auto was = g_keys.find(id);
            if (now_key == keys.end() || (was != g_keys.end() && was->second != now_key->second))
                drop.push_back(d.user);
        }
        g_keys = keys;
        g_keys_set = true;
    }
    for (LONG u : drop) NET_ECMS_ForceLogout(u);
    return "{\"keys\":" + std::to_string(keys.size()) + "}";
}

static std::string apply_want(const std::string& body) {
    std::map<std::string, Want> want;
    std::istringstream in(body);
    for (std::string line; std::getline(in, line);) {
        std::istringstream l(line);
        Want w;
        if (!(l >> w.dev >> w.channel >> w.type >> w.target)) continue;
        if (!safe_name(w.dev) || !safe_name(w.target, 128) || w.channel < 1 || w.channel > 512 || w.type < 0 || w.type > 1)
            continue;
        want[w.dev + " " + std::to_string(w.channel) + " " + std::to_string(w.type)] = w;
    }
    {
        std::lock_guard<std::mutex> lk(g_mu);
        g_want = want;
    }
    g_wake.notify_all();
    return "{\"want\":" + std::to_string(want.size()) + "}";
}

static void reply(int c, int code, const std::string& body) {
    std::string head = "HTTP/1.1 " + std::to_string(code) + (code == 200 ? " OK" : " Error") +
                       "\r\nContent-Type: application/json\r\nContent-Length: " + std::to_string(body.size()) +
                       "\r\nConnection: close\r\n\r\n";
    std::string all = head + body;
    for (size_t sent = 0; sent < all.size();) {
        ssize_t n = send(c, all.data() + sent, all.size() - sent, MSG_NOSIGNAL);
        if (n <= 0) break;
        sent += (size_t)n;
    }
}

static void handle(int c) {
    timeval tv{5, 0};
    setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    std::string req;
    char buf[8192];
    size_t head_end = std::string::npos, need = 0;
    while (req.size() < (1u << 20)) {
        ssize_t n = recv(c, buf, sizeof buf, 0);
        if (n <= 0) break;
        req.append(buf, (size_t)n);
        if (head_end == std::string::npos && (head_end = req.find("\r\n\r\n")) != std::string::npos) {
            std::string lower = req.substr(0, head_end);
            for (auto& ch : lower) ch = (char)tolower((unsigned char)ch);
            size_t cl = lower.find("content-length:");
            need = head_end + 4 + (cl == std::string::npos ? 0 : (size_t)atol(lower.c_str() + cl + 15));
        }
        if (head_end != std::string::npos && req.size() >= need) break;
    }
    if (head_end == std::string::npos) return reply(c, 400, "{\"error\":\"bad request\"}");
    std::string method, path;
    std::istringstream(req.substr(0, req.find("\r\n"))) >> method >> path;
    if (!g_api_token.empty()) {
        std::string head = req.substr(0, head_end), lower = head;
        for (auto& ch : lower) ch = (char)tolower((unsigned char)ch);
        size_t t = lower.find("\r\nx-bridge-token:");
        std::string got;
        if (t != std::string::npos) {
            size_t a = t + 17, e = head.find("\r\n", a);
            got = head.substr(a, e == std::string::npos ? std::string::npos : e - a);
            got.erase(0, got.find_first_not_of(' '));
            got.erase(got.find_last_not_of(" \r") + 1);
        }
        if (got != g_api_token) return reply(c, 401, "{\"error\":\"token\"}");
    }
    std::string body = req.substr(head_end + 4);
    if (method == "GET" && path == "/health") return reply(c, 200, "{\"ok\":true}");
    if (method == "GET" && path == "/devices") return reply(c, 200, devices_json());
    if (method == "PUT" && path == "/keys") return reply(c, 200, apply_keys(body));
    if (method == "PUT" && path == "/want") return reply(c, 200, apply_want(body));
    reply(c, 404, "{\"error\":\"not found\"}");
}

static std::atomic<int> g_http_busy{0};

static void http_server() {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_ANY);
    a.sin_port = htons((uint16_t)g_api_port);
    if (bind(fd, (sockaddr*)&a, sizeof a) < 0 || listen(fd, 32) < 0) {
        LOG("API port %d is not available", g_api_port);
        exit(1);
    }
    while (true) {
        int c = accept(fd, nullptr, nullptr);
        if (c < 0) continue;
        if (g_http_busy >= 16) {  // slow clients must not pile up threads
            close(c);
            continue;
        }
        g_http_busy++;
        std::thread([c] {
            handle(c);
            close(c);
            g_http_busy--;
        }).detach();
    }
}

// --- start ------------------------------------------------------------------------------

int main() {
    signal(SIGPIPE, SIG_IGN);
    g_public_ip = env("PUBLIC_IP", "");
    g_cms_port = atoi(env("CMS_PORT", "17660").c_str());
    g_stream_port = atoi(env("STREAM_PORT", "17661").c_str());
    g_api_port = atoi(env("API_PORT", "8091").c_str());
    g_api_token = env("API_TOKEN", "");
    g_rtsp_base = env("RTSP_BASE", "rtsp://go2rtc:8554");
    if (g_public_ip.empty()) {
        LOG("PUBLIC_IP is not set: devices would not know where to send video");
        return 1;
    }

    std::string lib = env("SDK_LIB", "/opt/isup/lib");
    std::string crypto = lib + "/libcrypto.so", ssl = lib + "/libssl.so";
    NET_ECMS_SetSDKInitCfg(NET_EHOME_CMS_INIT_CFG_LIBEAY_PATH, (void*)crypto.c_str());
    NET_ECMS_SetSDKInitCfg(NET_EHOME_CMS_INIT_CFG_SSLEAY_PATH, (void*)ssl.c_str());
    NET_ESTREAM_SetSDKInitCfg(NET_EHOME_ESTREAM_INIT_CFG_LIBEAY_PATH, (void*)crypto.c_str());
    NET_ESTREAM_SetSDKInitCfg(NET_EHOME_ESTREAM_INIT_CFG_SSLEAY_PATH, (void*)ssl.c_str());
    if (!NET_ECMS_Init() || !NET_ESTREAM_Init()) {
        LOG("SDK init failed");
        return 1;
    }
    char logdir[] = "/opt/isup/logs/";
    NET_ECMS_SetLogToFile(2, logdir, TRUE);
    NET_ESTREAM_SetLogToFile(2, logdir, TRUE);

    // 0 accepts every protocol version (a keyless registration is still
    // refused in ENUM_DEV_ON); 2 accepts only the secure 4.0+ handshake.
    NET_EHOME_LOCAL_ACCESS_SECURITY sec{};
    sec.dwSize = sizeof sec;
    int access = atoi(env("ACCESS_SECURITY", "0").c_str());
    sec.byAccessSecurity = (BYTE)(access == 2 ? 2 : 0);
    NET_ECMS_SetSDKLocalCfg(ACTIVE_ACCESS_SECURITY, &sec);
    NET_ESTREAM_SetSDKLocalCfg(ACTIVE_ACCESS_SECURITY, &sec);
    NET_ESTREAM_SetExceptionCallBack(0, nullptr, on_stream_exception, nullptr);

    NET_EHOME_LISTEN_PREVIEW_CFG preview{};
    snprintf(preview.struIPAdress.szIP, sizeof preview.struIPAdress.szIP, "0.0.0.0");
    preview.struIPAdress.wPort = (WORD)g_stream_port;
    preview.fnNewLinkCB = on_new_link;
    preview.byLinkMode = 0;
    if (NET_ESTREAM_StartListenPreview(&preview) < 0) {
        LOG("cannot listen for video on %d: %u", g_stream_port, NET_ESTREAM_GetLastError());
        return 1;
    }
    NET_EHOME_CMS_LISTEN_PARAM cms{};
    snprintf(cms.struAddress.szIP, sizeof cms.struAddress.szIP, "0.0.0.0");
    cms.struAddress.wPort = (WORD)g_cms_port;
    cms.fnCB = on_register;
    cms.dwKeepAliveSec = 15;
    cms.dwTimeOutCount = 4;
    if (NET_ECMS_StartListen(&cms) < 0) {
        LOG("cannot listen for registrations on %d: %u", g_cms_port, NET_ECMS_GetLastError());
        return 1;
    }
    LOG("ISUP bridge ready: registration %d tcp/udp, video %d tcp, api %d, public address %s",
        g_cms_port, g_stream_port, g_api_port, g_public_ip.c_str());

    std::thread(http_server).detach();
    supervisor();
    return 0;
}
