import type { ChartSpec } from "../api/types";

/** The chart's data as a real table: the screen-reader view and the "show data" view. */
export function DataTable({ spec, id }: { spec: ChartSpec; id: string }) {
  return (
    <table id={id} className="w-full border-collapse text-sm">
      <caption className="sr-only">{`${spec.title}: ${spec.period.label}`}</caption>
      <thead>
        <tr>
          {spec.table.columns.map((column) => (
            <th
              key={column}
              scope="col"
              className="border-b border-[var(--border)] px-2 py-1 text-left font-medium"
            >
              {column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {spec.table.rows.map((row, rowIndex) => (
          <tr key={rowIndex}>
            {row.map((cell, cellIndex) => (
              <td key={cellIndex} className="px-2 py-1">
                {cell ?? (
                  <>
                    <span aria-hidden="true">—</span>
                    <span className="sr-only">no value</span>
                  </>
                )}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
