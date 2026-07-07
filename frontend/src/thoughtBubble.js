/**
 * thoughtBubble.js
 * ─────────────────
 * Renders thought bubbles above characters using CSS2DRenderer.
 * Each bubble shows a portrait thumbnail + caption text.
 *
 * Setup (once):
 *   import { initThoughtBubbles, updateThoughtBubbles } from './thoughtBubble.js';
 *   const tbRenderer = initThoughtBubbles(container);   // call after main renderer
 *
 * Per frame:
 *   updateThoughtBubbles(scene, camera, characters, tbRenderer);
 *
 * characters: array of { mesh: THREE.Object3D, data: characterData }
 *
 * character.data must have:
 *   thought_bubble: {
 *     active: bool,
 *     subject_name: string,
 *     portrait_url: string | null,
 *     type: "crush"|"daydream"|"intention"|"worry"|"idol",
 *     caption: string,
 *     tick_expires: int,
 *   }
 */

import * as THREE from 'three';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

// ── Tunables ──────────────────────────────────────────────────────────────────
const BUBBLE_HEIGHT_OFFSET = 2.4;   // world units above character origin
const FADE_TICKS           = 30;    // ticks before expiry to start fading

// Type → border colour
const TYPE_COLORS = {
    crush:     '#ff6b8a',
    daydream:  '#a78bfa',
    idol:      '#fbbf24',
    intention: '#60a5fa',
    worry:     '#f87171',
    default:   '#e5e7eb',
};

// ── Internal state ────────────────────────────────────────────────────────────
const _bubbleMap = new Map();   // characterId → CSS2DObject

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * initThoughtBubbles(container)
 * Sets up a CSS2DRenderer layered over the main canvas.
 * Returns the renderer — store it and pass to updateThoughtBubbles each frame.
 */
export function initThoughtBubbles(container) {
    const renderer = new CSS2DRenderer();
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.domElement.style.position = 'absolute';
    renderer.domElement.style.top      = '0';
    renderer.domElement.style.left     = '0';
    renderer.domElement.style.pointerEvents = 'none';
    container.appendChild(renderer.domElement);

    window.addEventListener('resize', () => {
        renderer.setSize(container.clientWidth, container.clientHeight);
    });
    return renderer;
}

/**
 * updateThoughtBubbles(scene, camera, characters, tbRenderer, currentTick)
 *
 * characters: array of { id, mesh, data }
 * currentTick: current sim tick (for fade calculation)
 */
export function updateThoughtBubbles(scene, camera, characters, tbRenderer, currentTick = 0) {
    const activeIds = new Set();

    for (const { id, mesh, data } of characters) {
        const tb = data?.thought_bubble;
        if (!tb?.active) {
            _removeBubble(id, scene);
            continue;
        }

        activeIds.add(id);
        let obj = _bubbleMap.get(id);

        if (!obj) {
            obj = _createBubbleObject(id);
            // Anchor point above character head
            const anchor = new THREE.Object3D();
            anchor.position.set(0, BUBBLE_HEIGHT_OFFSET, 0);
            mesh.add(anchor);
            anchor.add(obj);
            scene.add(anchor);   // anchor is child of mesh, so it follows
            _bubbleMap.set(id, obj);
        }

        _updateBubbleContent(obj, tb, currentTick);
    }

    // Remove stale bubbles for characters no longer in scene
    for (const [id] of _bubbleMap) {
        if (!activeIds.has(id)) _removeBubble(id, scene);
    }

    tbRenderer.render(scene, camera);
}

/**
 * clearThoughtBubble(characterId, scene)
 * Explicitly dismiss a bubble (e.g. when character starts talking).
 */
export function clearThoughtBubble(characterId, scene) {
    _removeBubble(characterId, scene);
}

// ── Internal helpers ──────────────────────────────────────────────────────────

function _createBubbleObject(characterId) {
    const div = document.createElement('div');
    div.className   = 'thought-bubble';
    div.dataset.cid = characterId;
    div.innerHTML   = _bubbleHTML('', null, '', 'default');
    _injectStyles();

    const obj = new CSS2DObject(div);
    return obj;
}

function _updateBubbleContent(obj, tb, currentTick) {
    const type       = tb.type       || 'default';
    const caption    = tb.caption    || '';
    const portrait   = tb.portrait_url || null;
    const name       = tb.subject_name || '';
    const tickExp    = tb.tick_expires || Infinity;

    // Fade near expiry
    const remaining = tickExp - currentTick;
    const opacity   = remaining < FADE_TICKS ? Math.max(0, remaining / FADE_TICKS) : 1;

    obj.element.style.opacity = opacity;
    obj.element.innerHTML     = _bubbleHTML(caption, portrait, name, type);
}

function _bubbleHTML(caption, portraitUrl, name, type) {
    const color   = TYPE_COLORS[type] || TYPE_COLORS.default;
    const imgHtml = portraitUrl
        ? `<img src="${portraitUrl}" alt="${name}" class="tb-portrait" />`
        : (name ? `<div class="tb-avatar">${name.charAt(0).toUpperCase()}</div>` : '');

    return `
        <div class="tb-inner" style="--tb-color:${color}">
            <div class="tb-content">
                ${imgHtml}
                <span class="tb-caption">${_escapeHtml(caption)}</span>
            </div>
            <div class="tb-tail"></div>
        </div>
    `;
}

function _removeBubble(id, scene) {
    const obj = _bubbleMap.get(id);
    if (!obj) return;
    obj.parent?.remove(obj);
    _bubbleMap.delete(id);
}

function _escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

let _stylesInjected = false;
function _injectStyles() {
    if (_stylesInjected) return;
    _stylesInjected = true;

    const style = document.createElement('style');
    style.textContent = `
        .thought-bubble {
            pointer-events: none;
            user-select: none;
        }
        .tb-inner {
            position: relative;
            background: rgba(255,255,255,0.95);
            border: 2.5px solid var(--tb-color, #e5e7eb);
            border-radius: 14px;
            padding: 6px 10px;
            display: flex;
            flex-direction: column;
            align-items: center;
            min-width: 90px;
            max-width: 160px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.18);
            transform: translateX(-50%);
            font-family: sans-serif;
        }
        .tb-content {
            display: flex;
            align-items: center;
            gap: 7px;
        }
        .tb-portrait {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            object-fit: cover;
            border: 2px solid var(--tb-color, #e5e7eb);
            flex-shrink: 0;
        }
        .tb-avatar {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            background: var(--tb-color, #e5e7eb);
            color: #fff;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            font-size: 16px;
            flex-shrink: 0;
        }
        .tb-caption {
            font-size: 11px;
            color: #1f2937;
            line-height: 1.35;
            text-align: left;
        }
        /* Bubble tail — small circles mimicking thought bubble style */
        .tb-tail {
            position: absolute;
            bottom: -22px;
            left: 50%;
            transform: translateX(-50%);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 2px;
        }
        .tb-tail::before,
        .tb-tail::after {
            content: '';
            background: rgba(255,255,255,0.95);
            border: 2px solid var(--tb-color, #e5e7eb);
            border-radius: 50%;
            display: block;
        }
        .tb-tail::before { width: 9px; height: 9px; }
        .tb-tail::after  { width: 5px; height: 5px; }
    `;
    document.head.appendChild(style);
}
