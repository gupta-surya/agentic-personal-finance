import { useState } from "react";
import { type AskResponse, askAgent } from "./api/client";
import { ChartFrame } from "./components/ChartFrame";
import { registerAllRenderers } from "./renderers";

registerAllRenderers();

const SUGGESTIONS = [
  "How much did I spend last month?",
  "Where did my money go?",
  "What's my cash flow?",
  "Show my spending trend",
];

type AskState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; answer: AskResponse };

export function Ask() {
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<AskState>({ status: "idle" });

  async function submit(text: string) {
    const q = text.trim();
    if (!q) return;
    setQuestion(q);
    setState({ status: "loading" });
    try {
      const answer = await askAgent(q);
      setState({ status: "ready", answer });
    } catch (error) {
      setState({ status: "error", message: error instanceof Error ? error.message : "Something went wrong." });
    }
  }

  return (
    <div className="space-y-4">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit(question);
        }}
        className="flex gap-2"
      >
        <input
          data-testid="ask-input"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about your spending…"
          aria-label="Ask about your spending"
          className="flex-1 rounded border border-[var(--border)] bg-[var(--surface)] px-3 py-2"
        />
        <button
          data-testid="ask-submit"
          type="submit"
          className="rounded bg-[var(--text)] px-4 py-2 text-[var(--surface)]"
        >
          Ask
        </button>
      </form>

      <div className="flex flex-wrap gap-2">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            onClick={() => void submit(suggestion)}
            className="rounded-full border border-[var(--border)] px-3 py-1 text-sm text-[var(--text-muted)]"
          >
            {suggestion}
          </button>
        ))}
      </div>

      {state.status === "loading" && (
        <p role="status" className="text-sm text-[var(--text-muted)]">
          Thinking…
        </p>
      )}
      {state.status === "error" && (
        <p role="alert" className="text-sm text-red-600">
          {state.message}
        </p>
      )}
      {state.status === "ready" && (
        <section className="space-y-3" data-testid="ask-answer">
          <p className="text-base">{state.answer.prose}</p>
          {state.answer.engine && (
            <p className="text-xs text-[var(--text-muted)]" data-testid="engine">
              answered by {state.answer.engine}
            </p>
          )}
          {!state.answer.grounded && (
            <p className="text-xs text-[var(--text-muted)]" data-testid="grounding-note">
              Showing the verified summary; an unverified figure was withheld.
            </p>
          )}
          {state.answer.chart_spec && (
            <ChartFrame state={{ status: "ready", spec: state.answer.chart_spec }} />
          )}
        </section>
      )}
    </div>
  );
}
