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
      roomLookup[`${til