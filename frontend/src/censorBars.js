/**
 * censorBars.js
 * ─────────────
 * Attaches mosaic censor bar planes to character skeleton bones.
 * Call once per character at load time, then call updateCensorBars()
 * each frame (or whenever character.is_nude / exposed_chest changes).
 *
 * Usage:
 *   import { attachCensorBars, updateCensorBars } from './censorBars.js';
 *
 *   // When character mesh is loaded:
 *   attachCensorBars(skinnedMesh, characterData);
 *
 *   // Each frame or on state change:
 *   updateCensorBars(skinnedMesh, characterData);
 *
 * Requirements:
 *   - skinnedMesh must be a THREE.SkinnedMesh with a skeleton.
 *   - Skeleton needs bones named like: Hips / mixamorigHips (crotch)
 *     and Spine1 / mixamorigSpine1 / Chest (chest).
 *   - characterData must have: sex, is_nude, exposed_chest.
 */

import * as THREE from 'three';

// ── Tunables ──────────────────────────────────────────────────────────────────
const MOSAIC_PIXEL_SIZE = 14;   // mosaic block size in pixels — higher = coarser

// Censor bar geometry sizes (world units, tune to your character scale)
const CROTCH_W = 0.28,  CROTCH_H = 0.20;
const CHEST_W  = 0.36,  CHEST_H  = 0.18;

// Bone name candidates — tried in order, first match wins
const CROTCH_BONES = ['Hips', 'mixamorigHips', 'Pelvis', 'pelvis', 'hip'];
const CHEST_BONES  = ['Spine1', 'mixamorigSpine1', 'Chest', 'chest', 'Spine2', 'mixamorigSpine2'];

// ── Internal marker ───────────────────────────────────────────────────────────
const CENSOR_USER_DATA_KEY = '__censorBars';

// ── Shader ────────────────────────────────────────────────────────────────────
function makeMosaicMaterial(renderTarget) {
    return new THREE.ShaderMaterial({
        uniforms: {
            tScene:     { value: renderTarget ? renderTarget.texture : null },
            pixelSize:  { value: MOSAIC_PIXEL_SIZE },
            resolution: { value: new THREE.Vector2(window.innerWidth, window.innerHeight) },
        },
        vertexShader: /* glsl */`
            varying vec2 vScreenUv;
            void main() {
                vec4 clip = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
                vScreenUv = (clip.xy / clip.w) * 0.5 + 0.5;
                gl_Position = clip;
            }
        `,
        fragmentShader: /* glsl */`
            uniform sampler2D tScene;
            uniform float pixelSize;
            uniform vec2 resolution;
            varying vec2 vScreenUv;
            void main() {
                vec2 fragCoord = vScreenUv * resolution;
                vec2 block  = floor(fragCoord / pixelSize) * pixelSize;
                vec2 uv     = block / resolution;
                gl_FragColor = texture2D(tScene, uv);
            }
        `,
        transparent: false,
        depthTest:   true,
        depthWrite:  false,
        side:        THREE.DoubleSide,
    });
}

/** Fallback solid black bar when no render target is available. */
function makeSolidMaterial() {
    return new THREE.MeshBasicMaterial({
        color:       0x111111,
        transparent: true,
        opacity:     0.92,
        depthWrite:  false,
        side:        THREE.DoubleSide,
    });
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * attachCensorBars(skinnedMesh, characterData, renderTarget?)
 *
 * Creates censor plane meshes and attaches them to the skeleton bones.
 * renderTarget is optional — if omitted, solid bars are used instead of mosaic.
 * Idempotent: safe to call multiple times.
 */
export function attachCensorBars(skinnedMesh, characterData, renderTarget = null) {
    if (!skinnedMesh || !skinnedMesh.skeleton) return;

    // Clean up previous bars if re-attaching
    detachCensorBars(skinnedMesh);

    const bars = {};
    const mat  = renderTarget ? makeMosaicMaterial(renderTarget) : makeSolidMaterial();

    // ── Crotch bar (all characters) ──────────────────────────────────────────
    const crotchBone = _findBone(skinnedMesh.skeleton, CROTCH_BONES);
    if (crotchBone) {
        const mesh = _makePlane(CROTCH_W, CROTCH_H, mat.clone());
        // Offset forward so it renders in front of geometry
        mesh.position.set(0, 0.02, 0.06);
        mesh.visible = false;
        crotchBone.add(mesh);
        bars.crotch = mesh;
    }

    // ── Chest bar (female / intersex only) ──────────────────────────────────
    const sex = (characterData.sex || '').toLowerCase();
    if (sex === 'female' || sex === 'intersex') {
        const chestBone = _findBone(skinnedMesh.skeleton, CHEST_BONES);
        if (chestBone) {
            const mesh = _makePlane(CHEST_W, CHEST_H, mat.clone());
            mesh.position.set(0, 0.04, 0.08);
            mesh.visible = false;
            chestBone.add(mesh);
            bars.chest = mesh;
        }
    }

    skinnedMesh.userData[CENSOR_USER_DATA_KEY] = bars;
    updateCensorBars(skinnedMesh, characterData);
}

/**
 * updateCensorBars(skinnedMesh, characterData)
 *
 * Show/hide the bars based on current nudity state.
 * Call every frame or whenever clothing changes.
 */
export function updateCensorBars(skinnedMesh, characterData) {
    if (!skinnedMesh) return;
    const bars = skinnedMesh.userData[CENSOR_USER_DATA_KEY];
    if (!bars) return;

    if (bars.crotch) {
        bars.crotch.visible = !!characterData.is_nude;
    }
    if (bars.chest) {
        bars.chest.visible = !!characterData.exposed_chest || !!characterData.is_nude;
    }
}

/**
 * updateRenderTarget(skinnedMesh, renderTarget)
 *
 * Call after each scene pre-render so the mosaic reads the latest frame.
 */
export function updateRenderTarget(skinnedMesh, renderTarget) {
    const bars = skinnedMesh?.userData[CENSOR_USER_DATA_KEY];
    if (!bars) return;
    for (const bar of Object.values(bars)) {
        if (bar.material?.uniforms?.tScene) {
            bar.material.uniforms.tScene.value = renderTarget.texture;
        }
        if (bar.material?.uniforms?.resolution) {
            bar.material.uniforms.resolution.value.set(
                renderTarget.width, renderTarget.height
            );
        }
    }
}

/**
 * detachCensorBars(skinnedMesh)
 *
 * Remove all censor planes from the skeleton and clean up.
 */
export function detachCensorBars(skinnedMesh) {
    const bars = skinnedMesh?.userData[CENSOR_USER_DATA_KEY];
    if (!bars) return;
    for (const bar of Object.values(bars)) {
        bar.parent?.remove(bar);
        bar.geometry.dispose();
        bar.material.dispose();
    }
    delete skinnedMesh.userData[CENSOR_USER_DATA_KEY];
}

// ── Render loop helper ────────────────────────────────────────────────────────

/**
 * renderWithCensors(renderer, scene, camera, renderTarget, characterMeshes)
 *
 * Drop-in render call that:
 *   1. Renders scene to renderTarget (so mosaic has something to sample).
 *   2. Renders scene normally to screen.
 *
 * characterMeshes: array of SkinnedMesh objects with censor bars attached.
 *
 * Usage:
 *   // Replace renderer.render(scene, camera) with:
 *   renderWithCensors(renderer, scene, camera, rt, meshes);
 */
export function renderWithCensors(renderer, scene, camera, renderTarget, characterMeshes) {
    // Pre-render to texture (censor bars are hidden so they don't appear in their own sample)
    for (const mesh of characterMeshes) {
        _setCensorVisibility(mesh, false);
    }
    renderer.setRenderTarget(renderTarget);
    renderer.render(scene, camera);

    // Main render to screen with censor bars visible
    for (const mesh of characterMeshes) {
        _restoreCensorVisibility(mesh);
    }
    renderer.setRenderTarget(null);
    renderer.render(scene, camera);
}

// ── Internals ─────────────────────────────────────────────────────────────────

function _makePlane(w, h, material) {
    return new THREE.Mesh(new THREE.PlaneGeometry(w, h), material);
}

function _findBone(skeleton, candidates) {
    for (const name of candidates) {
        const bone = skeleton.getBoneByName(name);
        if (bone) return bone;
    }
    return null;
}

function _setCensorVisibility(mesh, visible) {
    const bars = mesh?.userData[CENSOR_USER_DATA_KEY];
    if (!bars) return;
    for (const bar of Object.values(bars)) {
        bar.userData.__prevVisible = bar.visible;
        bar.visible = visible;
    }
}

function _restoreCensorVisibility(mesh) {
    const bars = mesh?.userData[CENSOR_USER_DATA_KEY];
    if (!bars) return;
    for (const bar of Object.values(bars)) {
        if (bar.userData.__prevVisible !== undefined) {
            bar.visible = bar.userData.__prevVisible;
        }
    }
}
