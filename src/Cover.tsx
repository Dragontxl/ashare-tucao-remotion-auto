import React from "react";
import { AbsoluteFill } from "remotion";

// cover.json 由 generate_meta.py 在渲染前生成；此处兜底防止缺失时 bundle 失败
let cover: any;
try {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  cover = require("./cover.json");
} catch {
  cover = {};
}

const FONT = '"Microsoft YaHei", "Noto Sans CJK SC", "PingFang SC", "Heiti SC", sans-serif';

export const Cover: React.FC = () => {
  const show = cover.show_name || "A股盘面吐槽大会";
  const title = cover.article_title || "今天这盘面";
  const stats: { label: string; value: string; tone?: string }[] = cover.stats || [];
  return (
    <AbsoluteFill style={{ backgroundColor: "#0a0e1c", fontFamily: FONT }}>
      <AbsoluteFill style={{ background: "linear-gradient(135deg,#0a0e1c 0%,#0d1530 48%,#131b3a 100%)" }} />
      <AbsoluteFill style={{ backgroundImage:
        "linear-gradient(rgba(120,150,220,0.055) 1px,transparent 1px),linear-gradient(90deg,rgba(120,150,220,0.055) 1px,transparent 1px)",
        backgroundSize: "64px 64px" }} />
      <div style={{ position: "absolute", width: 900, height: 900, borderRadius: "50%", left: -260, top: -320,
        background: "radial-gradient(circle, rgba(255,60,90,0.20) 0%, transparent 66%)", filter: "blur(30px)" }} />
      <div style={{ position: "absolute", width: 980, height: 980, borderRadius: "50%", right: -300, bottom: -380,
        background: "radial-gradient(circle, rgba(64,110,255,0.22) 0%, transparent 66%)", filter: "blur(30px)" }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at center, transparent 40%, rgba(2,5,14,0.70) 100%)" }} />

      <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
        {cover.episode && (
          <div style={{ padding: "14px 34px", borderRadius: 999,
            background: "linear-gradient(90deg,#ff3b5c,#ff7a45)",
            fontSize: 30, fontWeight: 800, color: "#fff", letterSpacing: 6,
            boxShadow: "0 10px 40px rgba(255,70,90,0.35)" }}>
            {cover.episode}{cover.date_label ? " · " + cover.date_label : ""}
          </div>
        )}
        <div style={{ marginTop: 62, fontSize: 138, fontWeight: 900, letterSpacing: 10, lineHeight: 1.15,
          backgroundImage: "linear-gradient(180deg,#fff5f5 0%,#ffd0d0 34%,#ff5a6e 78%,#ff2e4d 100%)",
          WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent",
          filter: "drop-shadow(0 8px 30px rgba(255,60,90,0.45))", textAlign: "center" }}>
          {show}
        </div>
        <div style={{ marginTop: 38, width: 620, height: 5, borderRadius: 5,
          background: "linear-gradient(90deg,transparent,#ff5a6e,transparent)" }} />
        <div style={{ marginTop: 36, fontSize: 66, fontWeight: 700, letterSpacing: 8,
          color: "#eaf1ff", textAlign: "center", textShadow: "0 4px 22px rgba(120,160,255,0.35)" }}>
          {title}
        </div>
        {cover.market_mood && (
          <div style={{ marginTop: 30, fontSize: 30, letterSpacing: 12, color: "#8fa4cc" }}>
            市场情绪 · {cover.market_mood}
          </div>
        )}
      </AbsoluteFill>

      {stats.length > 0 && (
        <div style={{ position: "absolute", bottom: 58, left: 0, right: 0,
          display: "flex", justifyContent: "center", gap: 74, fontSize: 34, fontWeight: 800, letterSpacing: 2 }}>
          {stats.map((s, i) => (
            <div key={i} style={{ color: s.tone === "up" ? "#ff4d5e" : s.tone === "down" ? "#25e08a" : "#eaf1ff" }}>
              {s.label} {s.value}
            </div>
          ))}
        </div>
      )}

      {cover.ticker && (
        <div style={{ position: "absolute", bottom: 14, left: 0, right: 0, height: 30,
          overflow: "hidden", textAlign: "center", fontSize: 20, letterSpacing: 4,
          color: "rgba(255,90,110,0.75)" }}>{cover.ticker}</div>
      )}
    </AbsoluteFill>
  );
};
