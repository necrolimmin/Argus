import { useEffect, useRef } from "react";

import { useUi } from "../lib/store";

/*
 * The watch behind the sign-in: a wall of cameras. The ones near the pointer
 * turn to it and their lenses light up; the far ones keep panning slowly on
 * their own, so the room is never unwatched. With no pointer (a phone, or a
 * still mouse) the attention wanders by itself.
 * Under prefers-reduced-motion the wall is drawn once, looking at the form.
 */

interface Cam {
  x: number;
  y: number;
  color: string;
  /** Its own clock for the idle pan and the recording light. */
  seed: number;
  /** Where it rests when nobody is near, and where it points now. */
  rest: number;
  angle: number;
  led: boolean;
}

type Rgb = [number, number, number];

function rgb(hex: string): Rgb {
  const h = hex.trim().replace("#", "");
  const n = parseInt(h.length === 3 ? h.replace(/./g, "$&$&") : h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function mix(a: Rgb, b: Rgb, t: number): Rgb {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

/** A stable pseudo-random number for a grid cell, so a resize does not reshuffle the wall. */
function noise(c: number, r: number) {
  const v = Math.sin(c * 127.1 + r * 311.7) * 43758.5453;
  return v - Math.floor(v);
}

/** The shortest way round from one angle to another. */
function turn(from: number, to: number) {
  return Math.atan2(Math.sin(to - from), Math.cos(to - from));
}

const STEP_X = 132;
const STEP_Y = 106;
const REACH = 400; // how far from the pointer a camera notices it
const BODY = 20; // how far the housing reaches in front of its joint
const HALF = 8; // half its height

export function ArgusCameras() {
  const ref = useRef<HTMLCanvasElement>(null);
  const theme = useUi((s) => s.theme);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const css = getComputedStyle(document.documentElement);
    const token = (name: string) => rgb(css.getPropertyValue(name));
    const iris = [token("--iris-1"), token("--iris-2"), token("--iris-3")];
    const gold = token("--accent");
    const housing = `rgb(${token("--bg").join(",")})`;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let w = 0;
    let h = 0;
    let cams: Cam[] = [];
    let frame = 0;
    const started = performance.now();
    const pointer = { x: 0, y: 0, at: -1e9 };
    const look = { x: 0, y: 0, set: false };

    const layout = () => {
      const box = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = box.width;
      h = box.height;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      cams = [];
      const cols = Math.ceil(w / STEP_X) + 1;
      const rows = Math.ceil(h / STEP_Y) + 1;
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const n = noise(c, r);
          const x = c * STEP_X + (r % 2 ? STEP_X / 2 : 0) + (n - 0.5) * 18;
          const y = r * STEP_Y + (noise(r, c) - 0.5) * 16 + 10;
          const along = Math.min(1, Math.max(0, x / Math.max(w, 1)));
          // The feather's colours run across the wall; one camera in nine is gold.
          const tint = n > 0.89 ? gold : along < 0.5 ? mix(iris[0], iris[1], along * 2) : mix(iris[1], iris[2], along * 2 - 1);
          // At rest a camera looks down and a little to one side, as on a wall.
          const rest = Math.PI / 2 + (noise(c + 7, r + 3) - 0.5) * 1.5;
          cams.push({ x, y, color: tint.map(Math.round).join(","), seed: n * 1000, rest, angle: rest, led: noise(c + 2, r + 9) > 0.45 });
        }
      }
    };

    const draw = (now: number) => {
      const t = now - started;
      // Where attention is: the pointer while it moves, a slow wander otherwise.
      const idle = now - pointer.at > 2600;
      const tx = idle ? w * (0.5 + 0.42 * Math.sin(t / 4100)) : pointer.x;
      const ty = idle ? h * (0.5 + 0.36 * Math.sin(t / 3300 + 1)) : pointer.y;
      if (!look.set || still) {
        look.x = still ? w / 2 : tx;
        look.y = still ? h / 2 : ty;
        look.set = true;
      } else {
        look.x += (tx - look.x) * 0.1;
        look.y += (ty - look.y) * 0.1;
      }

      ctx.clearRect(0, 0, w, h);
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      for (const cam of cams) {
        const dx = look.x - cam.x;
        const dy = look.y - cam.y;
        const dist = Math.hypot(dx, dy) || 1;
        const near = still ? 0.6 : Math.max(0, 1 - dist / REACH);
        const eased = near * near * (3 - 2 * near);
        // They switch on one after another, left to right, when the page arrives.
        const wake = still ? 1 : Math.min(1, Math.max(0, (t - 100 - (cam.x / Math.max(w, 1)) * 650 - (cam.seed % 220)) / 420));

        // A far camera pans on its own; a near one turns to what it noticed.
        const pan = cam.rest + (still ? 0 : 0.5 * Math.sin(t / 2600 + cam.seed));
        const want = pan + turn(pan, Math.atan2(dy, dx)) * (still ? 1 : eased);
        cam.angle = still ? want : cam.angle + turn(cam.angle, want) * 0.12;

        const alpha = (0.26 + 0.7 * eased) * wake;
        const line = `rgba(${cam.color},${alpha})`;

        ctx.save();
        ctx.translate(cam.x, cam.y);

        // The bracket on the wall, then the housing on its joint.
        ctx.strokeStyle = line;
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        ctx.moveTo(-7, -15);
        ctx.lineTo(7, -15);
        ctx.moveTo(0, -15);
        ctx.lineTo(0, 0);
        ctx.stroke();

        ctx.rotate(cam.angle);
        ctx.beginPath();
        ctx.fillStyle = housing;
        // The lens barrel first, so the housing overlaps its back end.
        ctx.beginPath();
        ctx.roundRect(BODY - 3, -5.5, 10, 11, 2.5);
        ctx.fill();
        ctx.stroke();
        ctx.beginPath();
        ctx.roundRect(-10, -HALF, BODY + 10, HALF * 2, 4.5);
        ctx.fill();
        ctx.stroke();

        // The glass at the front: lit when the camera has something to look at.
        const glass = BODY + 7;
        ctx.beginPath();
        ctx.ellipse(glass, 0, 2.6, 5.5, 0, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${cam.color},${Math.min(1, alpha + 0.15)})`;
        ctx.fill();
        if (eased > 0.15) {
          // Its light falls a little way ahead.
          const beam = ctx.createLinearGradient(glass, 0, glass + 46, 0);
          beam.addColorStop(0, `rgba(${cam.color},${0.34 * eased * wake})`);
          beam.addColorStop(1, `rgba(${cam.color},0)`);
          ctx.beginPath();
          ctx.moveTo(glass + 2, -4);
          ctx.lineTo(glass + 46, -15);
          ctx.lineTo(glass + 46, 15);
          ctx.lineTo(glass + 2, 4);
          ctx.closePath();
          ctx.fillStyle = beam;
          ctx.fill();
          ctx.beginPath();
          ctx.arc(glass - 0.4, -2, 0.9, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(255,255,255,${0.9 * eased * wake})`;
          ctx.fill();
        }

        // The recording light at the back; it blinks on its own clock.
        if (cam.led) {
          const on = still || Math.sin(t / 520 + cam.seed) > -0.2;
          ctx.beginPath();
          ctx.arc(-4.5, 0, 1.6, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(240,101,93,${(on ? 0.35 + 0.6 * eased : 0.12) * wake})`;
          ctx.fill();
        }
        ctx.restore();
      }
      if (!still) frame = requestAnimationFrame(draw);
    };

    const move = (e: PointerEvent) => {
      const box = canvas.getBoundingClientRect();
      pointer.x = e.clientX - box.left;
      pointer.y = e.clientY - box.top;
      pointer.at = performance.now();
    };

    const resize = new ResizeObserver(() => {
      layout();
      if (still) draw(performance.now());
    });
    resize.observe(canvas);
    layout();
    if (still) draw(performance.now());
    else {
      frame = requestAnimationFrame(draw);
      window.addEventListener("pointermove", move, { passive: true });
    }
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      window.removeEventListener("pointermove", move);
    };
  }, [theme]);

  return <canvas ref={ref} className="argus-cameras" aria-hidden />;
}
