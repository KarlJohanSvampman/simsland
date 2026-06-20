export function generateNavigationGrid(floorplan){

  const blocked = new Set();

  // =====================================
  // BLOCKED WALLS
  // =====================================

  for(const key in floorplan.tiles){

    const tile =
      floorplan.tiles[key];

    const [x, y] =
      key.split(",").map(Number);

    const walls =
      tile.walls || {};

    for(const side in walls){

      const wall = walls[side];

      if(!wall) continue;

      if(wall.type === "wall"){

        blocked.add(`${x},${y}`);
      }
    }
  }

  // =====================================
  // DOORS REMOVE BLOCK
  // =====================================

  for(const door of floorplan.doors || []){

    blocked.delete(
      `${door.x},${door.y}`
    );
  }

  // =====================================
  // WALKABLE
  // =====================================

  const walkable = [];

  for(let x=0;x<floorplan.width;x++){

    for(let y=0;y<floorplan.height;y++){

      const key = `${x},${y}`;

      if(!blocked.has(key)){

        walkable.push({
          x,
          y
        });
      }
    }
  }

  floorplan.navigation = {

    blocked: [...blocked],

    walkable
  };

  return floorplan.navigation;
}