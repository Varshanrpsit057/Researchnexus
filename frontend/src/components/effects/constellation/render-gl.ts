/* WebGL2 renderer: draws the same `Frame` as the Canvas 2D renderer, with
 * the same colours, sizes, sprite and draw order, in five instanced draw
 * calls instead of thousands of canvas calls, and with rasterization on the
 * GPU. Edges are anti-aliased analytically in the fragment shaders (the
 * exact pixel coverage of a hairline, a square or a disc -- what Canvas 2D
 * computes), so no MSAA buffer is needed.
 *
 * Returns null where WebGL2 is missing or would only run in software
 * (`failIfMajorPerformanceCaveat`), and the caller falls back to Canvas 2D. */

import {
  HALO_ALPHA,
  LINK_COLORS,
  LINK_WIDTH_DEVICE_PX,
  NODE_BUCKETS,
  NODE_CODES,
  NODE_COLORS,
  TRAIL_COLOR,
  type Rgba,
} from "./field";
import type { Renderer } from "./render-2d";
import { makeGlowSprite, type AnyCanvas } from "./sprite";

// Curved backbone links are drawn as this many straight segments; at their
// length (at most ~104px) that is indistinguishable from the true curve.
const CURVE_SEGMENTS = 8;
const TRAIL_CODE = NODE_CODES; // the trail dot colour follows the node colours

const premul = ([r, g, b, a]: Rgba) => [(r / 255) * a, (g / 255) * a, (b / 255) * a, a];

const SEGMENT_VS = `#version 300 es
in vec2 a_corner;   // x: 0..1 along the segment, y: -1..1 across it
in vec4 a_ends;     // ax, ay, bx, by in CSS px
in float a_code;
uniform vec2 u_res;
uniform float u_dpr;
uniform float u_half; // half the quad's thickness in device px
uniform vec4 u_colors[12];
out float v_dist;
out vec4 v_color;
void main() {
  vec2 a = a_ends.xy * u_dpr;
  vec2 b = a_ends.zw * u_dpr;
  vec2 d = b - a;
  float len = length(d);
  vec2 dir = len > 1e-4 ? d / len : vec2(1.0, 0.0);
  vec2 p = mix(a, b, a_corner.x) + vec2(-dir.y, dir.x) * (a_corner.y * u_half);
  v_dist = a_corner.y * u_half;
  v_color = u_colors[int(a_code)];
  vec2 clip = p / u_res * 2.0 - 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
}`;

const SEGMENT_FS = `#version 300 es
precision mediump float;
in float v_dist;
in vec4 v_color;
uniform float u_width; // line width in device px
out vec4 o;
void main() {
  // coverage of this pixel by a line u_width wide, box-filtered across it
  float cov = clamp(u_width * 0.5 + 0.5 - abs(v_dist), 0.0, min(u_width, 1.0));
  o = v_color * cov;
}`;

const SPRITE_VS = `#version 300 es
in vec2 a_corner;   // 0..1
in vec4 a_sprite;   // x, y, size (CSS px), alpha
uniform vec2 u_res;
uniform float u_dpr;
out vec2 v_uv;
out float v_alpha;
void main() {
  vec2 p = (a_sprite.xy + (a_corner - 0.5) * a_sprite.z) * u_dpr;
  v_uv = a_corner;
  v_alpha = a_sprite.w;
  vec2 clip = p / u_res * 2.0 - 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
}`;

const SPRITE_FS = `#version 300 es
precision mediump float;
in vec2 v_uv;
in float v_alpha;
uniform sampler2D u_tex;
out vec4 o;
void main() {
  o = texture(u_tex, v_uv) * v_alpha;
}`;

const SHAPE_VS = `#version 300 es
in vec2 a_corner;   // -1..1
in vec4 a_shape;    // x, y, radius (CSS px), colour code
uniform vec2 u_res;
uniform float u_dpr;
uniform vec4 u_colors[9];
out vec2 v_local;
out float v_r;
flat out int v_square;
out vec4 v_color;
void main() {
  float r = a_shape.z * u_dpr;
  float extent = r + 1.0;
  int code = int(a_shape.w);
  v_local = a_corner * extent;
  v_r = r;
  v_square = code < ${NODE_BUCKETS} ? 1 : 0;
  v_color = u_colors[code];
  vec2 p = a_shape.xy * u_dpr + v_local;
  vec2 clip = p / u_res * 2.0 - 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
}`;

const SHAPE_FS = `#version 300 es
precision mediump float;
in vec2 v_local;
in float v_r;
flat in int v_square;
in vec4 v_color;
out vec4 o;
void main() {
  float cov;
  if (v_square == 1) {
    // exact area of this pixel covered by the square [-r, r]^2
    vec2 lo = max(v_local - 0.5, vec2(-v_r));
    vec2 hi = min(v_local + 0.5, vec2(v_r));
    vec2 span = clamp(hi - lo, 0.0, 1.0);
    cov = span.x * span.y;
  } else {
    cov = clamp(v_r - length(v_local) + 0.5, 0.0, 1.0);
  }
  if (cov <= 0.0) discard;
  o = v_color * cov;
}`;

function compile(gl: WebGL2RenderingContext, vs: string, fs: string): WebGLProgram | null {
  const program = gl.createProgram();
  const shaders = [
    [gl.VERTEX_SHADER, vs],
    [gl.FRAGMENT_SHADER, fs],
  ] as const;
  for (const [type, src] of shaders) {
    const shader = gl.createShader(type);
    if (!shader) return null;
    gl.shaderSource(shader, src);
    gl.compileShader(shader);
    gl.attachShader(program, shader);
    gl.deleteShader(shader);
  }
  gl.linkProgram(program);
  return gl.getProgramParameter(program, gl.LINK_STATUS) ? program : null;
}

interface Pass {
  program: WebGLProgram;
  vao: WebGLVertexArrayObject;
  instances: WebGLBuffer;
  u: Record<string, WebGLUniformLocation | null>;
}

/** Growable Float32 staging array for one pass's instance data. */
class Staging {
  data = new Float32Array(4096);
  length = 0;
  reset() {
    this.length = 0;
  }
  reserve(extra: number) {
    if (this.length + extra > this.data.length) {
      let size = this.data.length * 2;
      while (size < this.length + extra) size *= 2;
      const next = new Float32Array(size);
      next.set(this.data.subarray(0, this.length));
      this.data = next;
    }
  }
}

export function createWebGLRenderer(canvas: AnyCanvas): Renderer | null {
  const gl = canvas.getContext("webgl2", {
    alpha: true,
    premultipliedAlpha: true,
    antialias: false,
    depth: false,
    stencil: false,
    preserveDrawingBuffer: false,
    powerPreference: "low-power",
    failIfMajorPerformanceCaveat: true,
  }) as WebGL2RenderingContext | null;
  if (!gl) return null;

  let dpr = 1;
  let lost = false;
  let segments: Pass | null = null;
  let sprites: Pass | null = null;
  let shapes: Pass | null = null;
  let texture: WebGLTexture | null = null;
  const segData = new Staging();
  const haloData = new Staging();
  const glowData = new Staging();
  const shapeData = new Staging();
  const nodeStart = new Int32Array(NODE_CODES + 1);

  function makePass(vs: string, fs: string, corners: number[], attr: string, attrSize: number, extra?: { name: string; size: number }, uniforms: string[] = []): Pass | null {
    const program = compile(gl!, vs, fs);
    if (!program) return null;
    const vao = gl!.createVertexArray();
    gl!.bindVertexArray(vao);
    const cornerBuf = gl!.createBuffer();
    gl!.bindBuffer(gl!.ARRAY_BUFFER, cornerBuf);
    gl!.bufferData(gl!.ARRAY_BUFFER, new Float32Array(corners), gl!.STATIC_DRAW);
    const cornerLoc = gl!.getAttribLocation(program, "a_corner");
    gl!.enableVertexAttribArray(cornerLoc);
    gl!.vertexAttribPointer(cornerLoc, 2, gl!.FLOAT, false, 0, 0);

    const instances = gl!.createBuffer();
    gl!.bindBuffer(gl!.ARRAY_BUFFER, instances);
    const stride = (attrSize + (extra?.size ?? 0)) * 4;
    const loc = gl!.getAttribLocation(program, attr);
    gl!.enableVertexAttribArray(loc);
    gl!.vertexAttribPointer(loc, attrSize, gl!.FLOAT, false, stride, 0);
    gl!.vertexAttribDivisor(loc, 1);
    if (extra) {
      const extraLoc = gl!.getAttribLocation(program, extra.name);
      gl!.enableVertexAttribArray(extraLoc);
      gl!.vertexAttribPointer(extraLoc, extra.size, gl!.FLOAT, false, stride, attrSize * 4);
      gl!.vertexAttribDivisor(extraLoc, 1);
    }
    gl!.bindVertexArray(null);
    const u: Pass["u"] = {};
    for (const name of ["u_res", "u_dpr", ...uniforms]) u[name] = gl!.getUniformLocation(program, name);
    return { program, vao, instances, u };
  }

  function init(): boolean {
    const strip01 = [0, 0, 1, 0, 0, 1, 1, 1];
    segments = makePass(SEGMENT_VS, SEGMENT_FS, [0, -1, 1, -1, 0, 1, 1, 1], "a_ends", 4, { name: "a_code", size: 1 }, ["u_half", "u_width", "u_colors"]);
    sprites = makePass(SPRITE_VS, SPRITE_FS, strip01, "a_sprite", 4, undefined, ["u_tex"]);
    shapes = makePass(SHAPE_VS, SHAPE_FS, [-1, -1, 1, -1, -1, 1, 1, 1], "a_shape", 4, undefined, ["u_colors"]);
    if (!segments || !sprites || !shapes) return false;

    const sprite = makeGlowSprite();
    if (!sprite) return false;
    texture = gl!.createTexture();
    gl!.bindTexture(gl!.TEXTURE_2D, texture);
    // premultiplied, like the canvas bitmap Canvas 2D draws from
    gl!.pixelStorei(gl!.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    gl!.texImage2D(gl!.TEXTURE_2D, 0, gl!.RGBA, gl!.RGBA, gl!.UNSIGNED_BYTE, sprite as TexImageSource);
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_MIN_FILTER, gl!.LINEAR);
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_MAG_FILTER, gl!.LINEAR);
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_WRAP_S, gl!.CLAMP_TO_EDGE);
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_WRAP_T, gl!.CLAMP_TO_EDGE);

    gl!.useProgram(segments.program);
    gl!.uniform4fv(segments.u.u_colors, LINK_COLORS.flatMap(premul));
    gl!.uniform1f(segments.u.u_width, LINK_WIDTH_DEVICE_PX);
    gl!.uniform1f(segments.u.u_half, LINK_WIDTH_DEVICE_PX / 2 + 1);
    gl!.useProgram(shapes.program);
    gl!.uniform4fv(shapes.u.u_colors, [...NODE_COLORS, TRAIL_COLOR].flatMap(premul));
    gl!.useProgram(sprites.program);
    gl!.uniform1i(sprites.u.u_tex, 0);

    gl!.disable(gl!.DEPTH_TEST);
    gl!.enable(gl!.BLEND);
    return true;
  }

  if (!init()) return null;

  const onLost = (e: Event) => {
    e.preventDefault();
    lost = true;
  };
  const onRestored = () => {
    lost = !init();
  };
  canvas.addEventListener("webglcontextlost", onLost);
  canvas.addEventListener("webglcontextrestored", onRestored);

  function upload(pass: Pass, staging: Staging) {
    gl!.bindBuffer(gl!.ARRAY_BUFFER, pass.instances);
    gl!.bufferData(gl!.ARRAY_BUFFER, staging.data.subarray(0, staging.length), gl!.STREAM_DRAW);
  }

  function setView(pass: Pass) {
    gl!.useProgram(pass.program);
    gl!.uniform2f(pass.u.u_res, gl!.drawingBufferWidth, gl!.drawingBufferHeight);
    gl!.uniform1f(pass.u.u_dpr, dpr);
    gl!.bindVertexArray(pass.vao);
  }

  return {
    name: "webgl2",
    resize(width, height, nextDpr) {
      dpr = nextDpr;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
    },
    draw(frame) {
      if (lost || !segments || !sprites || !shapes) return;
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA); // source-over, premultiplied

      // links: straight ones as one segment, curved ones as a short polyline
      const L = frame.links;
      const [lax, lay, lbx, lby, lcx, lcy, lcode, lcurved] = L.cols;
      segData.reset();
      segData.reserve(L.count * 5 * CURVE_SEGMENTS);
      const s = segData.data;
      let o = 0;
      for (let e = 0; e < L.count; e++) {
        const code = lcode[e];
        if (!lcurved[e]) {
          s[o++] = lax[e];
          s[o++] = lay[e];
          s[o++] = lbx[e];
          s[o++] = lby[e];
          s[o++] = code;
          continue;
        }
        let x0 = lax[e];
        let y0 = lay[e];
        for (let k = 1; k <= CURVE_SEGMENTS; k++) {
          const u = k / CURVE_SEGMENTS;
          const iu = 1 - u;
          const x1 = iu * iu * lax[e] + 2 * iu * u * lcx[e] + u * u * lbx[e];
          const y1 = iu * iu * lay[e] + 2 * iu * u * lcy[e] + u * u * lby[e];
          s[o++] = x0;
          s[o++] = y0;
          s[o++] = x1;
          s[o++] = y1;
          s[o++] = code;
          x0 = x1;
          y0 = y1;
        }
      }
      segData.length = o;
      setView(segments);
      upload(segments, segData);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, o / 5);

      // steady halos under the major nodes
      const H = frame.halos;
      const [hx, hy, hs] = H.cols;
      haloData.reset();
      haloData.reserve(H.count * 4);
      for (let k = 0, h = 0; k < H.count; k++) {
        haloData.data[h++] = hx[k];
        haloData.data[h++] = hy[k];
        haloData.data[h++] = hs[k];
        haloData.data[h++] = HALO_ALPHA;
        haloData.length = h;
      }
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      setView(sprites);
      upload(sprites, haloData);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, H.count);

      // nodes in style-code order (majors over minors, as Canvas 2D draws
      // them), then the pulse trail dots
      const N = frame.nodes;
      const [nx, ny, nr, ncode] = N.cols;
      const D = frame.dots;
      const [dx, dy, dr] = D.cols;
      shapeData.reset();
      shapeData.reserve((N.count + D.count) * 4);
      const sh = shapeData.data;
      nodeStart.fill(0);
      for (let i = 0; i < N.count; i++) nodeStart[ncode[i] + 1]++;
      for (let c = 0; c < NODE_CODES; c++) nodeStart[c + 1] += nodeStart[c];
      for (let i = 0; i < N.count; i++) {
        const at = nodeStart[ncode[i]]++ * 4;
        sh[at] = nx[i];
        sh[at + 1] = ny[i];
        sh[at + 2] = nr[i];
        sh[at + 3] = ncode[i];
      }
      let p = N.count * 4;
      for (let k = 0; k < D.count; k++) {
        sh[p++] = dx[k];
        sh[p++] = dy[k];
        sh[p++] = dr[k];
        sh[p++] = TRAIL_CODE;
      }
      shapeData.length = p;
      setView(shapes);
      upload(shapes, shapeData);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, N.count + D.count);

      // additive bloom ("lighter") on flashing nodes and pulse heads
      const G = frame.glows;
      if (G.count > 0) {
        const [gx, gy, gs, ga] = G.cols;
        glowData.reset();
        glowData.reserve(G.count * 4);
        for (let k = 0, g = 0; k < G.count; k++) {
          glowData.data[g++] = gx[k];
          glowData.data[g++] = gy[k];
          glowData.data[g++] = gs[k];
          glowData.data[g++] = ga[k];
          glowData.length = g;
        }
        gl.blendFunc(gl.ONE, gl.ONE);
        setView(sprites);
        upload(sprites, glowData);
        gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, G.count);
      }
      gl.bindVertexArray(null);
    },
    dispose() {
      canvas.removeEventListener("webglcontextlost", onLost);
      canvas.removeEventListener("webglcontextrestored", onRestored);
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    },
  };
}
