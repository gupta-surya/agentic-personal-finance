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
    <div className="ask">
      <form
        className="ask-form"
        onSubmit={(event) => {
          event.preventDefault();
          void submit(question);
        }}
      >
        <input
          data-testid="ask-input"
          className="ask-input"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about your spending…"
          aria-label="Ask about your spending"
        />
        <button data-testid="ask-submit" type="submit" className="btn ask-send">
          Ask
        </button>
      </form>

      <div className="ask-suggestions">
        {SUGGESTIONS.map((suggestion) => (
          <button key={suggestion} type="button" className="chip ask-chip" onClick={() => void submit(suggestion)}>
            {suggestion}
          </button>
        ))}
      </div>

      {state.status === "loading" && (
        <p role="status" className="sub ask-status">
          Thinking…
        </p>
      )}
      {state.status === "error" && (
        <section className="card ask-error" role="alert">
          <h2 className="title">Something went wrong</h2>
          <p className="sub" style={{ marginTop: 4 }}>
            {state.message}
          </p>
          <button type="button" className="btn" style={{ marginTop: 12 }} onClick={() => void submit(question)}>
            Try again
          </button>
        </section>
      )}
      {state.status === "ready" && (
        <section className="ask-answer" data-testid="ask-answer">
          <p className="ask-prose">{state.answer.prose}</p>
          {!state.answer.grounded && (
            <p className="sub" data-testid="grounding-note">
              Showing the verified summary; an unverified figure was withheld.
            </p>
          )}
          {state.answer.chart_spec && <ChartFrame state={{ status: "ready", spec: state.answer.chart_spec }} />}
        </section>
      )}
    </div>
  );
}
