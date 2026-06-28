// Builds a room adjacency graph by finding door edges that sit between two rooms.
//
// Doors are stored as wall types on tiles, not as a separate array. We scan
// every wall edge with type === "door", find the tile on the other side of that
// edge, and connect the two rooms that contain those tiles.

const OPPOSITE = { north: "south", south: "north", east: "west", west: "east" };
const DELTA    = { north: [0,-1], south: [0,1], east: [1,0], west: [-1,0] };

export function generateRoomGraph(floorplan) {
  const graph = {};

  for (const room of floorplan.rooms) {
    graph[room.id] = { neighbors: [] };
  }

  // Build tile → room lookup
  const roomLookup = {};
  for (const room of floorplan.rooms) {
    for (const tile of room.tiles) {
      roomLookup[`${tile.x},${tile.y}`] = room.id;
    }
  }

  const connected = new Set(); // deduplicate edges

  for (const key in (floorplan.tiles || {})) {
    const tile    = floorplan.tiles[key];
    const [x, y] = key.split(",").map(Number);

    for (const [side, wall] of Object.entries(tile.walls || {})) {
      if (!wall || wall.type !== "door") continue;

      const [dx, dy] = DELTA[side];
      const nKey     = `${x + dx},${y + dy}`;

      const aRoom = roomLookup[key];
      const bRoom = roomLookup[nKey];

      if (!aRoom || !bRoom || aRoom === bRoom) continue;

      const edgeKey = [aRoom, bRoom].sort().join("|");
      if (connected.has(edgeKey)) continue;
      connected.add(edgeKey);

      if (graph[aRoom]) graph[aRoom].neighbors.push(bRoom);
      if (graph[bRoom]) graph[bRoom].neighbors.push(aRoom);
    }
  }

  floorplan.roomGraph = graph;
  return graph;
}
