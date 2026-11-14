import type { ChartSpec } from "../api/types";

/** The chart's data as a real table: the screen-reader view and the "Table" view. */
export function DataTable({ spec, id }: { spec: ChartSpec; id: string }) {
  return (
    <table id={id} className="datatable">
      <caption className="sr-only">{`${spec.title}${spec.period ? `: ${spec.period.label}` : ""}`}</caption>
      <thead>
        <tr>
          {spec.table.columns.map((column) => (
            <th key={column} scope="col">
              {column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {spec.table.rows.map((row, rowIndex) => (
          <tr key={rowIndex}>
            {row.map((cell, cellIndex) => (
              <td key={cellIndex}>
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
