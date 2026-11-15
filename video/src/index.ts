import { continueRender, delayRender, registerRoot, staticFile } from "remotion";
import { Root } from "./Root";

const waiting = delayRender("Loading IBM Plex Sans");
Promise.all(
  [400, 500, 600, 700].map((w) =>
    new FontFace("IBM Plex Sans", `url(${staticFile(`fonts/ibm-plex-sans-latin-${w}-normal.woff2`)}) format("woff2")`, {
      weight: String(w),
    })
      .load()
      .then((f) => document.fonts.add(f)),
  ),
).then(() => continueRender(waiting));

registerRoot(Root);
