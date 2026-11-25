import React from "react";
import { Composition } from "remotion";
import { StockVideo } from "./StockVideo";
import { Cover } from "./Cover";
import tl from "./timeline.json";
import cfg from "./config.json";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="StockRecap"
        component={StockVideo}
        durationInFrames={tl.totalFrames}
        fps={tl.fps}
        width={cfg.width || 1920}
        height={cfg.height || 1080}
      />
      <Composition
        id="Cover"
        component={Cover}
        durationInFrames={1}
        fps={30}
        width={cfg.width || 1920}
        height={cfg.height || 1080}
      />
    </>
  );
};
