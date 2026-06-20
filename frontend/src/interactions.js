import * as THREE from "three";

// =========================
// FIND ANCHOR
// =========================
export function findAnchor(prop, name) {

  return prop.anchors.find(
    a => a.name === name
  );
}


// =========================
// WORLD POSITION
// =========================
export function getAnchorWorldPosition(anchor) {

  const pos = new THREE.Vector3();

  anchor.object.getWorldPosition(pos);

  return pos;
}


// =========================
// PLAY PROP ANIMATION
// =========================
export function playPropAnimation(
  prop,
  interactionTemplate,
  phase
) {

  if(!interactionTemplate) return;

  const anims =
    interactionTemplate.animations || {};

  let clipName = null;

  if(phase === "start"){
    clipName = anims.start;
  }
  else if(phase === "loop"){
    clipName = anims.loop;
  }
  else if(phase === "stop"){
    clipName = anims.stop;
  }
  else if(phase === "interrupt"){
    clipName = anims.interrupted;
  }

  if(!clipName) return;

  const action =
    prop.actions[
      clipName.toLowerCase()
    ];

  if(!action) return;

  // stop others
  Object.values(prop.actions).forEach(a => {

    if(a !== action){
      a.fadeOut(0.2);
    }
  });

  action.reset();
  action.fadeIn(0.2);
  action.play();
}