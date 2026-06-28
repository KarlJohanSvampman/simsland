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

  return false;
}

export function detectRooms(floorplan) {
  const tiles   = floorplan.tiles || {};
  const visited = new Set();
  const rooms   = [];

  function floodFill(startX, startY) {
    const queue     = [[startX, startY]];
    const roomTiles = [];
    visited.add(`${startX},${startY}`);

    while (queue.length) {
      const [x, y] = queue.shift();
      roomTiles.push({ x, y });

      for (const [side, [dx, dy]] of Object.entries(NEIGHBOR_DELTA)) {
        const nx   = x + dx;
        const ny   = y + dy;
        const nKey = `${nx},${ny}`;

        if (visited.has(nKey)) continue;
        if (!tiles[nKey]?.floor) continue;          // neighbor has no floor
        if (edgeBlocked(tiles, x, y, side)) {
          visited.add(nKey);                         // wall blocks — don't cross but mark visited
          continue;
        }

        visited.add(nKey);
        queue.push([nx, ny]);
      }
    }

    return roomTiles;
  }

  for (const key in tiles) {
    if (visited.has(key)) continue;
    if (!tiles[key]?.floor) continue;

    const [x, y] = key.split(",").map(Number);
    const roomTiles = floodFill(x, y);

    if (roomTiles.length < 2) continue;

    rooms.push({
      id:    crypto.randomUUID(),
      type:  "room",
      tiles: roomTiles,
      tags:  [],
    });
  }

  floorplan.rooms = rooms;
  return rooms;
}
