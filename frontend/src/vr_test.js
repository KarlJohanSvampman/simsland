// src/vr_test.js
//
// Standalone WebXR sanity check -- deliberately has zero dependency on
// main.js/operator_view.js's sim-viewer complexity (orthographic desktop
// camera, character models, director-mode gestures, ...). Exists purely
// to answer one question in isolation: does THIS browser, on THIS device,
// over THIS connection, actually get a working immersive-vr session at
// all? If this page works and operator_view.html doesn't, the bug is in
// the app; if this page also fails, it's the environment/connection
// (secure-context origin, runtime, headset) -- see the two frontend
// commits alongside this file for the real fix in each case.

import * as THREE from "three";
import { VRButton } from "three/examples/jsm/webxr/VRButton.js";
import { XRControllerModelFactory } from "three/examples/jsm/webxr/XRControllerModelFactory.js";

const statusLine = document.getElementById("statusLine");

if (navigator.xr) {
  navigator.xr.isSessionSupported("immersive-vr").then((supported) => {
    statusLine.textContent = supported
      ? "immersive-vr supported -- click \"ENTER VR\" below."
      : "navigator.xr exists but immersive-vr is NOT supported here.";
  }).catch((err) => {
    statusLine.textContent = `isSessionSupported threw: ${err.message}`;
  });
} else {
  statusLine.textContent =
    "navigator.xr is undefined -- either an insecure origin (WebXR requires " +
    "https:// or http://localhost, see this page's own docstring) or a " +
    "browser/runtime with no WebXR support at all.";
}

const canvas = document.getElementById("c");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.xr.enabled = true;
document.body.appendChild(VRButton.createButton(renderer));

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x202030);

// Desktop preview camera (mirrors what the headset sees once presenting --
// three.js's WebXRManager swaps in the device's own stereo cameras
// automatically while a session is active, same mechanism main.js relies
// on for its own perspective/orthographic swap).
const desktopCamera = new THREE.PerspectiveCamera(70, window.innerWidth / window.innerHeight, 0.05, 100);
desktopCamera.position.set(0, 1.6, 3);

scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 1.2));
const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
dirLight.position.set(2, 4, 2);
scene.add(dirLight);

const grid = new THREE.GridHelper(20, 20, 0x6688aa, 0x334455);
scene.add(grid);

const cubeGeometry = new THREE.BoxGeometry(0.4, 0.4, 0.4);
const cubeMaterial = new THREE.MeshStandardMaterial({ color: 0x4caf50 });
const cube = new THREE.Mesh(cubeGeometry, cubeMaterial);
cube.position.set(0, 1.2, -1);
scene.add(cube);

// Controllers -- ray + grip model, same shape as main.js's XR setup, just
// without any raycast/selection logic on top (nothing to select here).
const controllerModelFactory = new XRControllerModelFactory();
const flashTimers = [null, null];
[0, 1].forEach((i) => {
  const controller = renderer.xr.getController(i);
  const rayGeometry = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(0, 0, -5),
  ]);
  const ray = new THREE.Line(rayGeometry, new THREE.LineBasicMaterial({ color: 0xffe066 }));
  controller.add(ray);
  controller.addEventListener("selectstart", () => {
    cubeMaterial.color.set(0xff4444);
    clearTimeout(flashTimers[i]);
    flashTimers[i] = setTimeout(() => cubeMaterial.color.set(0x4caf50), 250);
  });
  scene.add(controller);

  const grip = renderer.xr.getControllerGrip(i);
  grip.add(controllerModelFactory.createControllerModel(grip));
  scene.add(grip);
});

window.addEventListener("resize", () => {
  desktopCamera.aspect = window.innerWidth / window.innerHeight;
  desktopCamera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

renderer.setAnimationLoop(() => {
  cube.rotation.x += 0.01;
  cube.rotation.y += 0.013;
  renderer.render(scene, desktopCamera);
});
