// The generated API types (src/api/schema.d.ts). expectTypeOf is checked by the compiler,
// so `npm run typecheck` fails when an operation or its response types change shape.
import { describe, expectTypeOf, it } from "vitest";

import type { components, paths } from "@/api/schema";

type Schemas = components["schemas"];
type Get<Path extends keyof paths> = paths[Path]["get"];

describe("generated API types", () => {
  it("type each operation's 200 body", () => {
    expectTypeOf<
      Get<"/healthz">["responses"][200]["content"]["application/json"]
    >().toEqualTypeOf<Schemas["ProbeStatus"]>();
    expectTypeOf<
      Get<"/readyz">["responses"][200]["content"]["application/json"]
    >().toEqualTypeOf<Schemas["ProbeStatus"]>();
    expectTypeOf<
      Get<"/api/v1/meta">["responses"][200]["content"]["application/json"]
    >().toEqualTypeOf<Schemas["ServerMeta"]>();
  });

  it("type /readyz's 503 body as ProbeStatus", () => {
    expectTypeOf<
      Get<"/readyz">["responses"][503]["content"]["application/json"]
    >().toEqualTypeOf<Schemas["ProbeStatus"]>();
  });

  it("type every operation's errors as problem details", () => {
    type ProblemContent = { "application/problem+json": Schemas["ProblemDetails"] };
    expectTypeOf<
      Get<"/healthz">["responses"]["default"]["content"]
    >().toEqualTypeOf<ProblemContent>();
    expectTypeOf<
      Get<"/readyz">["responses"]["default"]["content"]
    >().toEqualTypeOf<ProblemContent>();
    expectTypeOf<
      Get<"/api/v1/meta">["responses"]["default"]["content"]
    >().toEqualTypeOf<ProblemContent>();
  });
});
