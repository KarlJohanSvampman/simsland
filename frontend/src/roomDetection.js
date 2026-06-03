export function detectRooms(floorplan){

  const width = floorplan.width;
  const height = floorplan.height;

  const walls = new Set();

  for(const tile of floorplan.tiles){

    if(tile.type === 'wall'){

      walls.add(`${tile.x},${tile.y}`);
    }
  }

  const visited = new Set();

  const rooms = [];

  function floodFill(startX, startY){

    const queue = [[startX, startY]];

    const roomTiles = [];

    visited.add(`${startX},${startY}`);

    while(queue.length){

      const [x,y] = queue.shift();

      roomTiles.push({x,y});

      const neighbors = [
        [x+1,y],
        [x-1,y],
        [x,y+1],
        [x,y-1]
      ];

      for(const [nx,ny] of neighbors){

        if(nx < 0 || ny < 0) continue;
        if(nx >= width || ny >= height) continue;

        const key = `${nx},${ny}`;

        if(visited.has(key)) continue;

        if(walls.has(key)) continue;

        visited.add(key);

        queue.push([nx,ny]);
      }
    }

    return roomTiles;
  }

  for(let x=0;x<width;x++){
    for(let y=0;y<height;y++){

      const key = `${x},${y}`;

      if(visited.has(key)) continue;

      if(walls.has(key)) continue;

      const tiles = floodFill(x,y);

      if(tiles.length < 4) continue;

      rooms.push({
        id: crypto.randomUUID(),
        type: 'room',
        tiles,
        tags: []
      });
    }
  }

  floorplan.rooms = rooms;

  return rooms;
}