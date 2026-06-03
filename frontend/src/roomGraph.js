export function generateRoomGraph(floorplan){

  const graph = {};

  for(const room of floorplan.rooms){

    graph[room.id] = {
      neighbors: []
    };
  }

  for(const door of floorplan.doors || []){

    const connected = [];

    for(const room of floorplan.rooms){

      for(const tile of room.tiles){

        const dx = Math.abs(tile.x - door.x);
        const dy = Math.abs(tile.y - door.y);

        if(dx + dy === 1){

          connected.push(room.id);
          break;
        }
      }
    }

    if(connected.length >= 2){

      const a = connected[0];
      const b = connected[1];

      graph[a].neighbors.push(b);
      graph[b].neighbors.push(a);
    }
  }

  floorplan.roomGraph = graph;

  return graph;
}