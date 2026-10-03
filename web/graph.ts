export interface Commit { sha: string; parents: string[]; date: string; subject: string }

// A small lane list is enough for the 60-commit local history window.
export function layoutGraph(commits: Commit[]) {
  const lanes: string[] = [];
  const nodes: {sha: string; lane: number; row: number}[] = [];
  for (const [row, commit] of commits.entries()) {
    let lane = lanes.indexOf(commit.sha);
    if (lane < 0) { lane = lanes.length; lanes.push(commit.sha); }
    nodes.push({sha: commit.sha, lane, row});
    lanes[lane] = commit.parents[0] || '';
    for (const parent of commit.parents.slice(1)) if (!lanes.includes(parent)) lanes.push(parent);
    // Empty lanes can be reused without moving existing branch columns.
    while (lanes.length && !lanes.at(-1)) lanes.pop();
  }
  const bySha = new Map(nodes.map(n => [n.sha, n]));
  const edges = commits.flatMap(c => c.parents.flatMap(parent => {
    const from = bySha.get(c.sha), to = bySha.get(parent);
    return from && to ? [{from, to}] : [];
  }));
  return {nodes, edges, lanes: Math.max(1, ...nodes.map(n => n.lane + 1))};
}
