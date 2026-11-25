import React from "react";
import {
  AbsoluteFill, Audio, Img, interpolate, spring, staticFile,
  useCurrentFrame, useVideoConfig,
} from "remotion";
import tl from "./timeline.json";
import cfg from "./config.json";
import manifest from "./charts_manifest.json";
import { assignCharts } from "./chartMatch";

type Tone = "negative" | "positive" | "warn" | "neutral";
type Item = {
  id: number; text: string; visual: string; big?: string; label?: string;
  tone: Tone; chart?: string; startFrame: number; endFrame: number;
};

const FONT = '"Microsoft YaHei", "Noto Sans CJK SC", "PingFang SC", "Heiti SC", sans-serif';

const TONE: Record<Tone, { main: string; glow: string; soft: string }> = {
  negative: { main: "#25e08a", glow: "rgba(37,224,138,0.30)", soft: "rgba(37,224,138,0.12)" },
  positive: { main: "#ff4d5e", glow: "rgba(255,77,94,0.30)", soft: "rgba(255,77,94,0.12)" },
  warn: { main: "#ffb02e", glow: "rgba(255,176,46,0.30)", soft: "rgba(255,176,46,0.12)" },
  neutral: { main: "#eef3ff", glow: "rgba(160,190,255,0.22)", soft: "rgba(160,190,255,0.10)" },
};

function bigFontSize(s = "") {
  if (s.length <= 3) return 200;
  if (s.length <= 6) return 150;
  if (s.length <= 10) return 108;
  return 82;
}

// 实际生成的图表清单（make_charts.py 写入）；null 表示未知，不做过滤（兼容旧数据）
const AVAILABLE: string[] | undefined =
  (manifest as { files?: string[] | null }).files ?? undefined;

// 全片统一分配图表：同一张图最多出现一次，避免多个镜头复用同一张图
const CHART_ASSIGN = assignCharts(tl.items as Item[], cfg.stocks || [], AVAILABLE);
const CHART_BY_ID = new Map<number, string>();
(tl.items as Item[]).forEach((item, i) => {
  const file = CHART_ASSIGN[i];
  if (file) CHART_BY_ID.set(item.id, file);
});

// 背景：深色渐变 + 网格 + 光斑 + 暗角 + 红色跑马灯
function Backdrop({ item }: { item: Item }) {
  const frame = useCurrentFrame();
  const drift = interpolate(frame, [0, tl.totalFrames], [0, 160], { extrapolateRight: "clamp" });
  const tint = TONE[item.tone];
  const ticker = cfg.ticker || "";
  const tickerX = interpolate(frame, [0, tl.totalFrames], [0, -1900], { extrapolateRight: "extend" });
  return (
    <AbsoluteFill style={{ backgroundColor: "#0a0e1c" }}>
      <div style={{ position: "absolute", inset: 0,
        background: "linear-gradient(135deg,#0a0e1c,#0d1530 48%,#131b3a)" }} />
      <div style={{ position: "absolute", inset: 0,
        backgroundImage: "linear-gradient(rgba(120,150,220,0.05) 1px,transparent 1px),linear-gradient(90deg,rgba(120,150,220,0.05) 1px,transparent 1px)",
        backgroundSize: "64px 64px" }} />
      <div style={{ position: "absolute", width: 700, height: 700, borderRadius: "50%",
        left: -240 + drift * 0.25, top: 620,
        background: `radial-gradient(circle, ${tint.glow} 0%, transparent 68%)`, filter: "blur(24px)" }} />
      <div style={{ position: "absolute", inset: 0,
        background: "radial-gradient(ellipse at center, transparent 42%, rgba(2,5,14,0.66) 100%)" }} />
      {/* 滚动快讯：醒目红色 */}
      {ticker && (
        <div style={{ position: "absolute", bottom: 18, left: 0, right: 0, height: 38,
          overflow: "hidden", fontFamily: FONT, fontSize: 24, fontWeight: 700,
          letterSpacing: 3, opacity: 0.85, color: "#ff5a6e", whiteSpace: "nowrap",
          textShadow: "0 0 14px rgba(255,70,100,0.55)",
          maskImage: "linear-gradient(90deg,transparent 0%,#000 6%,#000 94%,transparent 100%)",
          WebkitMaskImage: "linear-gradient(90deg,transparent 0%,#000 6%,#000 94%,transparent 100%)" }}>
          <div style={{ transform: `translateX(${tickerX}px)` }}>{ticker.repeat(4)}</div>
        </div>
      )}
    </AbsoluteFill>
  );
}

function TopBar({ item }: { item: Item }) {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [0, tl.totalFrames], [0, 100], { extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", top: 0, left: 0, right: 0, padding: "34px 64px 0" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <div style={{ padding: "10px 20px", borderRadius: 8,
            background: "linear-gradient(90deg,#ff3b5c,#ff7a45)",
            fontFamily: FONT, fontSize: 24, fontWeight: 800, color: "#fff", letterSpacing: 2 }}>
            {cfg.show_name || "盘面吐槽大会"}
          </div>
          <div style={{ fontFamily: FONT, fontSize: 22, color: "#8fa4cc", letterSpacing: 2 }}>
            {cfg.episode}{cfg.episode ? " · " : ""}{cfg.date_label || "A股复盘"}
          </div>
        </div>
        <div style={{ fontFamily: FONT, fontSize: 22, color: "#8fa4cc",
          border: "1px solid rgba(143,164,204,0.35)", borderRadius: 999, padding: "8px 22px" }}>
          市场情绪：{cfg.market_mood || "—"}
        </div>
      </div>
      <div style={{ marginTop: 22, height: 6, borderRadius: 6,
        background: "rgba(255,255,255,0.10)", overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${p}%`,
          background: "linear-gradient(90deg,#ff3b5c,#ffb02e,#25e08a)" }} />
      </div>
      <div style={{ marginTop: 14, fontFamily: FONT, fontSize: 18, color: "#66779b", letterSpacing: 1 }}>
        SCENE {String(item.id).padStart(2, "0")} / {tl.items.length}
      </div>
    </div>
  );
}

function useEnter(item: Item, delay = 0) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const rel = Math.max(0, frame - item.startFrame - delay);
  const s = spring({ frame: rel, fps, config: { damping: 14, mass: 0.7, stiffness: 120 } });
  const out = interpolate(frame, [item.endFrame - 6, item.endFrame + 4], [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return { s, out, rel };
}

// 伪随机：同一个镜头每次渲染结果一致（Remotion 必须可复现）
function seededRand(seed: number) {
  const x = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
}

type ImgMotion = {
  transform: string;
  opacity: number;
  filter?: string;
  clipPath?: string;
  transformOrigin?: string;
};

// 图片入场动画：8 种风格，按镜头 id 稳定随机
function imgEntrance(kind: number, rel: number, fps: number): ImgMotion {
  const s = spring({ frame: rel, fps, config: { damping: 15, mass: 0.75, stiffness: 110 } });
  const p = interpolate(rel, [0, 16], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const d = 1 - s;
  switch (kind % 8) {
    case 0: // 右侧 3D 翻转入场
      return {
        opacity: p, transformOrigin: "left center",
        transform: `perspective(1600px) rotateY(${d * 74}deg) translateX(${d * 140}px)`,
      };
    case 1: // 冲击缩放 + 去模糊
      return {
        opacity: p, filter: `blur(${d * 16}px)`,
        transform: `scale(${1.26 - 0.26 * s})`,
      };
    case 2: // 底部上浮 + 轻微回正
      return {
        opacity: p, transformOrigin: "center bottom",
        transform: `translateY(${d * 240}px) rotate(${d * -7}deg) scale(${0.92 + 0.08 * s})`,
      };
    case 3: // 从左到右擦除揭示
      return {
        opacity: 1, clipPath: `inset(0 ${(1 - p) * 100}% 0 0)`,
        transform: `scale(${0.96 + 0.04 * s})`,
      };
    case 4: // 摆锤式甩入
      return {
        opacity: p, transformOrigin: "top center",
        transform: `rotate(${d * -14}deg) scale(${0.88 + 0.12 * s})`,
      };
    case 5: { // 故障闪烁 + 横向抖动
      const flick = rel < 14 ? (Math.sin(rel * 3.7) > 0 ? 1 : 0.35) : 1;
      return {
        opacity: p * flick,
        transform: `translateX(${d * Math.sin(rel * 2.3) * 26}px) scale(${0.94 + 0.06 * s})`,
      };
    }
    case 6: // 仰角翻起（rotateX）
      return {
        opacity: p, transformOrigin: "center bottom",
        transform: `perspective(1200px) rotateX(${d * 58}deg) translateY(${d * 90}px)`,
      };
    default: // 斜向旋冲
      return {
        opacity: p, filter: `blur(${d * 6}px)`,
        transform: `translate(${d * 130}px, ${d * 90}px) rotate(${d * 10}deg) scale(${0.82 + 0.18 * s})`,
      };
  }
}

function ChartScene({ item, chart }: { item: Item; chart: string }) {
  const { s, out, rel } = useEnter(item);
  const { fps } = useVideoConfig();
  const c = TONE[item.tone];
  const big = item.big ?? "";
  // 每个镜头稳定随机一种入场动画
  const kind = Math.floor(seededRand(item.id * 3.7 + 1.3) * 8);
  const motion = imgEntrance(kind, rel, fps);
  // 入场后卡片轻微漂浮，增加画面呼吸感
  const float = Math.sin(rel * 0.06) * 5;
  // 一道扫光掠过图表
  const sweepX = interpolate(rel, [6, 24], [-45, 145], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", padding: "0 90px", gap: 60, opacity: out }}>
      <div style={{ width: 700, flexShrink: 0,
        transform: `translateX(${(1 - s) * -50}px)`, fontFamily: FONT }}>
        {big && <div style={{ fontSize: bigFontSize(big) * 0.72, fontWeight: 900, color: c.main,
          lineHeight: 1.08, letterSpacing: -2, textShadow: `0 0 34px ${c.glow}`,
          whiteSpace: "nowrap" }}>{big}</div>}
        <div style={{ marginTop: 20, fontSize: 34, color: "#c3d0ee", letterSpacing: 3, fontWeight: 600 }}>
          {item.label}
        </div>
        <div style={{ marginTop: 30, fontSize: 26, color: "#8fa4cc", lineHeight: 1.5, letterSpacing: 1 }}>
          {item.text}
        </div>
      </div>
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{
          transform: motion.transform, opacity: motion.opacity, filter: motion.filter,
          clipPath: motion.clipPath, transformOrigin: motion.transformOrigin,
          willChange: "transform, opacity, filter",
        }}>
          <div style={{ position: "relative", padding: 22, background: "rgba(12,18,38,0.86)",
            border: "2px solid rgba(140,170,230,0.28)", borderRadius: 24,
            boxShadow: `0 24px 80px rgba(0,0,0,0.55), 0 0 60px ${c.glow}`,
            transform: `translateY(${float}px)` }}>
            <Img src={staticFile(chart)} style={{ width: 980, height: 690, objectFit: "contain", borderRadius: 12 }} />
            {/* 扫光 */}
            <div style={{ position: "absolute", inset: 0, borderRadius: 24, overflow: "hidden", pointerEvents: "none" }}>
              <div style={{ position: "absolute", top: "-12%", bottom: "-12%", width: "30%", left: `${sweepX}%`,
                background: "linear-gradient(90deg, transparent, rgba(180,210,255,0.28), transparent)",
                transform: "skewX(-18deg)" }} />
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
}

function DataScene({ item }: { item: Item }) {
  const { s, out } = useEnter(item);
  const c = TONE[item.tone];
  const big = item.big ?? "";
  // 无核心数字时降级为居中文案卡，避免空白大字
  if (!big) {
    return (
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: out }}>
        <div style={{ maxWidth: 1500, padding: "0 110px", textAlign: "center", fontFamily: FONT,
          transform: `translateY(${(1 - s) * 40}px)` }}>
          <div style={{ fontSize: 74, fontWeight: 900, color: c.main, lineHeight: 1.35,
            textShadow: `0 0 36px ${c.glow}` }}>{item.text}</div>
        </div>
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: out }}>
      <div style={{ position: "absolute", width: 1180, height: 380, borderRadius: 28,
        background: `radial-gradient(ellipse at center, ${c.glow} 0%, transparent 70%)`,
        transform: `scale(${0.8 + s * 0.2})` }} />
      <div style={{ transform: `translateY(${(1 - s) * 60}px) scale(${0.86 + s * 0.14})`,
        textAlign: "center", fontFamily: FONT }}>
        <div style={{ fontSize: bigFontSize(big), fontWeight: 900, color: c.main,
          letterSpacing: -4, lineHeight: 1.05, textShadow: `0 0 42px ${c.glow}, 0 8px 0 rgba(0,0,0,0.28)`,
          whiteSpace: "nowrap" }}>{big}</div>
        <div style={{ marginTop: 26, fontSize: 34, color: "#c3d0ee", letterSpacing: 6, fontWeight: 600 }}>
          {item.label}
        </div>
      </div>
    </AbsoluteFill>
  );
}

function PunchScene({ item }: { item: Item }) {
  const { s, out, rel } = useEnter(item);
  const c = TONE[item.tone];
  const chars = Array.from(item.text);
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: out }}>
      <div style={{ position: "absolute", fontSize: 420, lineHeight: 1, color: c.soft,
        fontFamily: "Georgia,serif", top: 120, left: 120 }}>“</div>
      <div style={{ maxWidth: 1500, padding: "0 90px", textAlign: "center",
        transform: `translateY(${(1 - s) * 46}px)`, fontFamily: FONT }}>
        {chars.map((ch, i) => {
          const shown = interpolate(rel, [i * 2.2, i * 2.2 + 10], [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
          return <span key={i} style={{ display: "inline-block", opacity: shown,
            transform: `translateY(${(1 - shown) * 18}px)`,
            fontSize: item.text.length > 24 ? 62 : item.text.length > 16 ? 76 : 92,
            fontWeight: 900, color: i < 4 ? c.main : "#f2f6ff",
            textShadow: "0 4px 24px rgba(0,0,0,0.45)" }}>{ch}</span>;
        })}
      </div>
    </AbsoluteFill>
  );
}

function TopicScene({ item }: { item: Item }) {
  const { s, out } = useEnter(item);
  const c = TONE[item.tone];
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: out }}>
      <div style={{ transform: `translateX(${(1 - s) * 320}px)`, display: "flex", alignItems: "center",
        gap: 40, padding: "44px 80px",
        background: `linear-gradient(90deg, ${c.soft}, transparent)`,
        borderLeft: `10px solid ${c.main}`, fontFamily: FONT }}>
        <div style={{ fontSize: 96, fontWeight: 900, color: c.main, letterSpacing: 8 }}>
          {item.label || item.text}
        </div>
        <div style={{ fontSize: 30, color: "#9fb2d8", letterSpacing: 3 }}>登场</div>
      </div>
    </AbsoluteFill>
  );
}

function TitleScene({ item }: { item: Item }) {
  const { s, out } = useEnter(item);
  const isOutro = item.visual === "outro";
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: out }}>
      <div style={{ transform: `scale(${0.7 + s * 0.3})`, textAlign: "center", fontFamily: FONT }}>
        {isOutro ? (
          <>
            <div style={{ fontSize: 118, fontWeight: 900, color: "#ffb02e", letterSpacing: 6,
              textShadow: "0 0 46px rgba(255,176,46,0.35)" }}>点赞收藏</div>
            <div style={{ marginTop: 24, fontSize: 62, fontWeight: 800, color: "#eef3ff", letterSpacing: 4 }}>
              明天接着渡劫 🤝</div>
            <div style={{ marginTop: 46, fontSize: 26, color: "#8fa4cc", letterSpacing: 4 }}>
              以上仅为复盘交流 · 不构成投资建议</div>
          </>
        ) : (
          <>
            <div style={{ fontSize: 40, color: "#ff6b7d", fontWeight: 800, letterSpacing: 14, marginBottom: 30 }}>
              今天的主题是</div>
            <div style={{ fontSize: 108, fontWeight: 900, color: "#ffb02e", letterSpacing: 4,
              textShadow: "0 0 50px rgba(255,176,46,0.4), 0 10px 0 rgba(0,0,0,0.3)" }}>
              《{cfg.hook_title || "今天这盘面"}》</div>
            <div style={{ marginTop: 34, fontSize: 30, color: "#9fb2d8", letterSpacing: 6 }}>
              {cfg.date_label || ""} · A股渡劫实录</div>
          </>
        )}
      </div>
    </AbsoluteFill>
  );
}

function LessonScene({ item }: { item: Item }) {
  const { s, out } = useEnter(item);
  const c = TONE[item.tone];
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: out }}>
      <div style={{ transform: `translateY(${(1 - s) * 40}px)`, width: 1320, padding: "44px 64px",
        boxSizing: "border-box",
        background: "linear-gradient(135deg,rgba(37,120,255,0.16),rgba(10,16,34,0.7))",
        border: "2px solid rgba(120,170,255,0.35)", borderRadius: 22, fontFamily: FONT }}>
        <div style={{ fontSize: 24, color: "#79b4ff", letterSpacing: 6, fontWeight: 700, marginBottom: 22 }}>
          ⚠ 正经时刻 · 风险提示</div>
        {item.big ? (
          <>
            <div style={{ fontSize: 52, fontWeight: 900, color: c.main, lineHeight: 1.25, letterSpacing: 4 }}>
              {item.big}</div>
            <div style={{ marginTop: 18, fontSize: item.text.length > 34 ? 30 : 34, fontWeight: 600,
              color: "#dfe8ff", lineHeight: 1.65, letterSpacing: 1 }}>{item.text}</div>
          </>
        ) : (
          <div style={{ fontSize: 58, fontWeight: 800, color: c.main, lineHeight: 1.35 }}>{item.text}</div>
        )}
      </div>
    </AbsoluteFill>
  );
}

function Subtitle({ item }: { item: Item }) {
  const { s, out } = useEnter(item, 0);
  return (
    <div style={{ position: "absolute", bottom: 96, left: 0, right: 0,
      display: "flex", justifyContent: "center", opacity: out }}>
      <div style={{ maxWidth: 1500, padding: "16px 40px", background: "rgba(4,8,20,0.72)",
        borderRadius: 14, border: "1px solid rgba(255,255,255,0.12)",
        transform: `translateY(${(1 - s) * 20}px)`, fontFamily: FONT, fontSize: 38,
        fontWeight: 600, color: "#ffffff", letterSpacing: 2, textAlign: "center",
        textShadow: "0 2px 8px rgba(0,0,0,0.8)" }}>{item.text}</div>
    </div>
  );
}

export const StockVideo: React.FC = () => {
  const frame = useCurrentFrame();
  const items = tl.items as Item[];
  let current: Item = items[0];
  for (let i = 0; i < items.length; i++) {
    if (frame >= items[i].startFrame) current = items[i];
    else break;
  }
  const chart = CHART_BY_ID.get(current.id) ?? null;
  return (
    <AbsoluteFill style={{ backgroundColor: "#0a0e1c" }}>
      <Audio src={staticFile("voiceover.mp3")} />
      <Backdrop item={current} />
      {chart ? <ChartScene item={current} chart={chart} /> : (
        <>
          {current.visual === "data" && <DataScene item={current} />}
          {current.visual === "text" && <DataScene item={current} />}
          {current.visual === "punch" && <PunchScene item={current} />}
          {current.visual === "topic" && <TopicScene item={current} />}
          {current.visual === "lesson" && <LessonScene item={current} />}
          {(current.visual === "hook" || current.visual === "title" || current.visual === "outro") && (
            <TitleScene item={current} />
          )}
        </>
      )}
      <TopBar item={current} />
      <Subtitle item={current} />
    </AbsoluteFill>
  );
};
