import { useEffect, useRef } from "react";

import { useUi } from "../lib/store";

/*
 * The hundred eyes of Argus. In the myth they never all sleep at once: here
 * the ones far from the pointer doze, half-lidded, and the ones near it open
 * and follow it. With no pointer (or on a phone) the watch wanders by itself.
 * Under prefers-reduced-motion the field is drawn once, looking at the form.
 */

interface Eye {
  x: number;
  y: number;
  color: string;
  /** Each eye dozes and blinks on its own clock. */
  seed: number;
  blinkAt: number;
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

/** A stable pseudo-random number for a grid cell, so a resize does not reshuffle the field. */
function noise(c: number, r: number) {
  const v = Math.sin(c * 127.1 + r * 311.7) * 43758.5453;
  return v - Math.floor(v);
}

const STEP_X = 104;
const STEP_Y = 78;
const HALF = 21; // half the width of an eye
const LID = 10.5; // half its height when wide open

export function ArgusEyes() {
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
    const pupil = `rgb(${token("--bg").join(",")})`;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let w = 0;
    let h = 0;
    let eyes: Eye[] = [];
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
      eyes = [];
      const cols = Math.ceil(w / STEP_X) + 1;
      const rows = Math.ceil(h / STEP_Y) + 1;
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const n = noise(c, r);
          const x = c * STEP_X + (r % 2 ? STEP_X / 2 : 0) + (n - 0.5) * 14;
          const y = r * STEP_Y + (noise(r, c) - 0.5) * 12 + 8;
          const along = Math.min(1, Math.max(0, x / Math.max(w, 1)));
          // The feather's colours run across the field; one eye in nine is the gold ring.
          const tint = n > 0.89 ? gold : along < 0.5 ? mix(iris[0], iris[1], along * 2) : mix(iris[1], iris[2], along * 2 - 1);
          eyes.push({ x, y, color: tint.map(Math.round).join(","), seed: n * 1000, blinkAt: 1500 + n * 9000 });
        }
      }
    };

    const draw = (now: number) => {
      const t = now - started;
      // Where the eyes look: the pointer while it moves, a slow wander otherwise.
      const idle = now - pointer.at > 2600;
      const tx = idle ? w * (0.5 + 0.4 * Math.sin(t / 3700)) : pointer.x;
      const ty = idle ? h * (0.42 + 0.3 * Math.sin(t / 2900 + 1)) : pointer.y;
      if (!look.set || still) {
        look.x = still ? w * 1.1 : tx;
        look.y = still ? h * 0.5 : ty;
        look.set = true;
      } else {
        look.x += (tx - look.x) * 0.09;
        look.y += (ty - look.y) * 0.09;
      }

      ctx.clearRect(0, 0, w, h);
      ctx.lineWidth = 1.6;
      ctx.lineCap = "round";
      for (const eye of eyes) {
        const dx = look.x - eye.x;
        const dy = look.y - eye.y;
        const dist = Math.hypot(dx, dy) || 1;
        const near = still ? 0.55 : Math.max(0, 1 - dist / 360);
        // They open one after another, left to right, when the page arrives.
        const wake = still ? 1 : Math.min(1, Math.max(0, (t - 120 - (eye.x / Math.max(w, 1)) * 700 - (eye.seed % 200)) / 420));
        const doze = still ? 0.75 : 0.34 + 0.2 * Math.sin(t / 2300 + eye.seed);
        let open = (doze + (1 - doze) * near * near * (3 - 2 * near)) * wake;
        if (!still) {
          const since = t - eye.blinkAt;
          if (since > 0) {
            if (since < 220) open *= Math.abs(since - 110) / 110;
            else eye.blinkAt = t + 2500 + ((eye.seed * 7919 + t) % 9000);
          }
        }
        const lid = Math.max(0.6, LID * open);
        const alpha = (0.2 + 0.7 * near) * wake;

        ctx.beginPath();
        ctx.moveTo(eye.x - HALF, eye.y);
        ctx.quadraticCurveTo(eye.x, eye.y - lid * 2, eye.x + HALF, eye.y);
        ctx.quadraticCurveTo(eye.x, eye.y + lid * 2, eye.x - HALF, eye.y);
        ctx.strokeStyle = `rgba(${eye.color},${alpha})`;
        ctx.stroke();

        if (open > 0.2) {
          const reach = Math.min(1, dist / 60) * 6.5;
          const ix = eye.x + (dx / dist) * reach;
          const iy = eye.y + (dy / dist) * reach * 0.55;
          ctx.save();
          ctx.clip();
          ctx.beginPath();
          ctx.arc(ix, iy, 7.6, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(${eye.color},${Math.min(1, alpha + 0.12)})`;
          ctx.fill();
          ctx.beginPath();
          ctx.arc(ix, iy, 3.1, 0, Math.PI * 2);
          ctx.fillStyle = pupil;
          ctx.fill();
          ctx.restore();
        }
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

  return <canvas ref={ref} className="argus-eyes" aria-hidden />;
}
