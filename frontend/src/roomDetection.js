// =========================================================
// ROOM DETECTION
// Flood-fills over tiles that have floors, treating solid
// walls as barriers between adjacent tiles. Door and window
// wall types are passable.
//
// Wall storage format:
//   floorplan.tiles["x,y"].walls = {
//     north: { type: "wall"|"door"|"window", material: ... } | null,
//     south: ..., east: ..., west: ...
//   }
//
// A wall on the north side of tile (x,y) is the same physical
// edge as a wall on the south side of tile (x,y-1). We check
// both sides to support one-sided wall painting.
// =========================================================

const OPPOSITE = { north: "south", south: "north", east: "west", west: "east" };
const NEIGHBOR_DELTA = {
  north: [  0, -1 ],
  south: [  0,  1 ],
  east:  [  1,  0 ],
  west:  [ -1,  0 ],
};

/**
 * Returns true if movement from (x,y) toward `side` is blocked by a solid wall.
 * Checks both the leaving tile's outgoing edge AND the entering tile's incoming edge.
 */
function edgeBlocked(tiles, x, y, side) {
  const key  = `${x},${y}`;
  const tile = tiles[key];

  // Outgoing wall on this tile
  const outWall = tile?.walls?.[side];
  if (outWall?.type === "wall") return true;

  // Incoming wall on the adjacent tile (opposite side)
  const [dx, dy] = NEIGHBOR_DELTA[side];
  const nKey  = `${x + dx},${y + dy}`;
  const nTile = tiles[nKey];
  const inWall = nTile?.walls?.[OPPOSITE[side]];
  if (inWall?.type === "wall") return true;