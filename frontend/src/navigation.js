// A tile is walkable if it has a floor. Wall edges restrict
// movement between adjacent tiles but don't make a tile itself unwalkable.
//
// Output:
//   floorplan.navigation = {
//     walkable:  [{x, y}, ...]        — tiles characters can stand on
//     blocked:   ["x,y", ...]         — tiles without floors
//     wallEdges: [{x, y, side, type}] — wall/door/window edge data for pathfinding
//   }

export function generateNavigationGrid(floorplan) {
  const tiles     = floorplan.tiles || {};
  const walkable  = [];
  const blocked   = [];
  const wallEdges = [];

  // Walkable / blocked from floor presence
  for (let x = 0; x < floorplan.width; x++) {
    for (let y = 0; y < floorplan.height; y++) {
      const key  = `${x},${y}`;
      const tile = tiles[key];
      if (tile?.floor) {
        walkable.push({ x, y });
      } else {
        blocked.push(key);
      }
    }
  }

  // Wall edges — tell pathfinder which transitions are gated by walls/doors/windows
  for (const key in tiles) {
    const tile    = tiles[key];
    const [x, y] = key.split(",").map(Number);
    for (const [side, wall] of Object.entries(tile.walls || {})) {
      if (wall) wallEdges.push({ x, y, side, type: wall.type });
    }
  }

  floorplan.navigation = { walkable, blocked, wallE