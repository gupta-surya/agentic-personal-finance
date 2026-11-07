import { ChartFrame } from "../components/ChartFrame";
import { getRenderer, registerRenderer } from "../renderers/registry";
import { emptySpec, swatchSpec, unknownTemplateSpec } from "./specs";
import { SwatchRenderer } from "./SwatchRenderer";

// Development only. Nothing outside src/dev imports this at build time: App loads it
// behind `import.meta.env.DEV`, so the production bundle has none of it
// (`npm run check:no-dev` fails the build if it does).

/** Frame states from canned specs: no API needed. Open with #/fixtures in `npm run dev`. */
export default function Fixtures() {
  if (!getRenderer("fixture_swatch")) registerRenderer("fixture_swatch", SwatchRenderer);
  return (
    <>
      <ChartFrame state={{ status: "ready", spec: swatchSpec }} />
      <ChartFrame state={{ status: "ready", spec: unknownTemplateSpec }} />
      <ChartFrame state={{ status: "ready", spec: emptySpec }} />
      <ChartFrame state={{ status: "loading" }} />
      <ChartFrame state={{ status: "error", message: "The render request failed (HTTP 422)." }} />
    </>
  );
}
