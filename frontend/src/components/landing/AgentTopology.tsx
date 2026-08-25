/**
 * components/landing/AgentTopology — the pipeline as a shape
 * ==========================================================
 * Nine nodes in run order, plus the one edge that makes this a pipeline rather
 * than a list: the repair branch from the Debugger back to the code-generating
 * agents. That loop is the product's actual argument — a linear chain of nine
 * prompts is not interesting, a chain that goes back and fixes its own output
 * is — and it is the one thing a row of chips cannot show.
 *
 * Inline SVG, no library, no animation. Every colour is a token, so it follows
 * the theme rather than pinning two hexes into the markup.
 *
 * Accessibility: the graphic is one `role="img"` with a written description.
 * Nine separately-focusable nodes would be nine tab stops carrying no
 * information the surrounding copy does not already give, and the labels are
 * drawn as SVG text so they are searchable and scale with the card.
 */

const NODES = [
  { n: 1, label: 'Intent'   },
  { n: 2, label: 'Plan'     },
  { n: 3, label: 'Arch'     },
  { n: 4, label: 'Backend'  },
  { n: 5, label: 'Frontend' },
  { n: 6, label: 'Debug'    },
  { n: 7, label: 'Review'   },
  { n: 8, label: 'Test'     },
  { n: 9, label: 'Docs'     },
] as const;

/* Serpentine: five across, drop, four back. A single row of nine at this card
   width puts the nodes ~30px apart, which is closer than their own labels. */
const TOP_Y = 38;
const BOT_Y = 118;
const COLS = [44, 132, 220, 308, 396];

const POS = [
  { x: COLS[0], y: TOP_Y }, { x: COLS[1], y: TOP_Y }, { x: COLS[2], y: TOP_Y },
  { x: COLS[3], y: TOP_Y }, { x: COLS[4], y: TOP_Y },
  { x: COLS[4], y: BOT_Y }, { x: COLS[3], y: BOT_Y }, { x: COLS[2], y: BOT_Y },
  { x: COLS[1], y: BOT_Y },
];

const R = 15;

export function AgentTopology() {
  return (
    <svg
      className="topo"
      viewBox="0 0 440 160"
      role="img"
      aria-label={
        'Pipeline topology: nine agents run in order — Intent Analyzer, Planner, '
        + 'Architect, Backend Developer, Frontend Generator, Debugger, Reviewer, '
        + 'Tester, Documenter — with a repair branch running from the Debugger '
        + 'back to the code-generating agents.'
      }
    >
      {/* Straight runs between consecutive nodes, drawn first so the nodes sit
          on top of them and no line shows through a fill. */}
      {POS.slice(0, -1).map((from, i) => {
        const to = POS[i + 1];
        const vertical = from.x === to.x;
        return (
          <line
            key={i}
            className="topo__edge"
            x1={vertical ? from.x : from.x + R}
            y1={vertical ? from.y + R : from.y}
            x2={vertical ? to.x : to.x - R}
            y2={vertical ? to.y - R : to.y}
          />
        );
      })}

      {/* The repair branch: Debugger → Backend Developer. Dashed, because it
          runs conditionally — only when something failed to import or run. */}
      <path
        className="topo__edge topo__edge--repair"
        d={`M ${POS[5].x - R} ${POS[5].y} C 250 ${BOT_Y}, 250 ${TOP_Y}, ${POS[3].x} ${POS[3].y + R}`}
        fill="none"
      />
      {/* Set to the left of the curve and right-aligned to it, not centred on
          it: a centred label lands directly on the dashed stroke, and the two
          then read as one broken glyph. */}
      <text className="topo__branch" x="238" y="82">repair loop</text>

      {NODES.map((node, i) => (
        <g key={node.n}>
          <circle className="topo__node" cx={POS[i].x} cy={POS[i].y} r={R} />
          <text className="topo__num" x={POS[i].x} y={POS[i].y + 3.5}>
            {node.n}
          </text>
          <text
            className="topo__label"
            x={POS[i].x}
            y={POS[i].y === TOP_Y ? POS[i].y - 24 : POS[i].y + 30}
          >
            {node.label}
          </text>
        </g>
      ))}
    </svg>
  );
}
