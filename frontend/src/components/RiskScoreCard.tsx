import type { RiskResult } from "@/lib/backend";
import { Card } from "@/components/ui/Card";

// CLAUDE.md §6: "The risk score reflects reporting history, not true quality. Say so wherever it
// is shown." Structural, not just written: there is no code path in this component that renders
// `result.score` without also rendering `result.meaning` right beside it - the two are one
// return statement, not two optional pieces a page could choose to show separately.
export function RiskScoreCard({ result }: { result: RiskResult }) {
  return (
    <Card className="space-y-3">
      <h2 className="text-lg font-semibold">Risk score</h2>
      {result.available && result.score !== null ? (
        <>
          <p className="text-3xl font-bold">{Math.round(result.score * 100)}%</p>
          {result.accuracyNote && <p className="text-sm font-medium">{result.accuracyNote}</p>}
          {result.explanation.length > 0 && (
            <ul className="list-disc space-y-1 pl-6 text-sm">
              {result.explanation.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
        </>
      ) : null}
      {/* Always rendered - the one sentence that must travel with the score, or in place of one. */}
      <p className="text-sm text-muted-foreground">{result.meaning}</p>
    </Card>
  );
}
