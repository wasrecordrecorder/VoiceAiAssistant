export class Orb {
  constructor(canvas) {
    this.canvas = canvas;
    this.gl = canvas.getContext("webgl", { alpha: true, antialias: true });
    this.level = 0;
    this.targetLevel = 0;
    this.mode = 0;
    this.targetMode = 0;
    this.impulse = 0;
    this.startedAt = performance.now();
    if (!this.gl) {
      return;
    }
    this.program = this.createProgram();
    this.position = this.gl.getAttribLocation(this.program, "a_position");
    this.time = this.gl.getUniformLocation(this.program, "u_time");
    this.resolution = this.gl.getUniformLocation(this.program, "u_resolution");
    this.audio = this.gl.getUniformLocation(this.program, "u_level");
    this.state = this.gl.getUniformLocation(this.program, "u_mode");
    this.buffer = this.gl.createBuffer();
    this.gl.bindBuffer(this.gl.ARRAY_BUFFER, this.buffer);
    this.gl.bufferData(this.gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), this.gl.STATIC_DRAW);
    this.render = this.render.bind(this);
    requestAnimationFrame(this.render);
  }

  createShader(type, source) {
    const shader = this.gl.createShader(type);
    this.gl.shaderSource(shader, source);
    this.gl.compileShader(shader);
    return shader;
  }

  createProgram() {
    const vertex = this.createShader(this.gl.VERTEX_SHADER, `
      attribute vec2 a_position;
      void main() {
        gl_Position = vec4(a_position, 0.0, 1.0);
      }
    `);
    const fragment = this.createShader(this.gl.FRAGMENT_SHADER, `
      precision highp float;
      uniform vec2 u_resolution;
      uniform float u_time;
      uniform float u_level;
      uniform float u_mode;

      float hash(vec2 p) {
        return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
      }

      float noise(vec2 p) {
        vec2 i = floor(p);
        vec2 f = fract(p);
        vec2 u = f * f * (3.0 - 2.0 * f);
        return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
      }

      float fbm(vec2 p) {
        float v = 0.0;
        float a = 0.54;
        for (int i = 0; i < 5; i++) {
          v += a * noise(p);
          p = p * 2.04 + vec2(17.3, 9.2);
          a *= 0.49;
        }
        return v;
      }

      void main() {
        vec2 uv = (gl_FragCoord.xy - 0.5 * u_resolution.xy) / min(u_resolution.x, u_resolution.y);
        float t = u_time;
        float energy = clamp(u_level, 0.0, 1.0);
        float active = smoothstep(0.2, 1.25, u_mode);
        float speaking = smoothstep(2.35, 3.0, u_mode) * (1.0 - smoothstep(3.1, 3.65, u_mode));
        float error = smoothstep(3.5, 4.0, u_mode);
        float speed = 0.19 + active * 0.24 + speaking * 0.2;
        float pulse = sin(t * (0.78 + active * 0.7)) * 0.009 + sin(t * 2.4) * 0.003;
        pulse += energy * (0.018 + speaking * 0.025);
        vec2 q = uv * (2.62 - energy * 0.06);
        float warp = fbm(q + vec2(t * speed, -t * speed * 0.54));
        float wave = sin(q.x * 4.0 + t * 1.32 + warp * 4.0) * cos(q.y * 3.2 - t * 0.83 + warp * 3.1);
        float radius = 0.322 + pulse + wave * (0.007 + energy * 0.024 + active * 0.004);
        float d = length(uv) - radius;
        float body = 1.0 - smoothstep(-0.014, 0.013, d);
        float halo = exp(-max(d, 0.0) * 14.0) * (0.11 + active * 0.07 + energy * 0.09);
        float z = sqrt(max(0.0, radius * radius - dot(uv, uv))) / radius;
        float texture = fbm(q * 1.65 + vec2(t * speed * 0.9, t * 0.29)) * 0.47 + wave * 0.14;
        float shade = 0.18 + z * 0.7 + texture * 0.29 + energy * 0.08;
        vec3 cold = vec3(0.19, 0.20, 0.23);
        vec3 silver = vec3(0.95, 0.96, 0.98);
        vec3 tone = mix(cold, silver, clamp(shade, 0.0, 1.0));
        tone = mix(tone, vec3(0.72, 0.36, 0.38), error * 0.53);
        vec3 glow = mix(vec3(0.41, 0.43, 0.49), vec3(0.72, 0.75, 0.82), active);
        glow = mix(glow, vec3(0.57, 0.26, 0.29), error);
        gl_FragColor = vec4(tone * body + glow * halo, body + halo);
      }
    `);
    const program = this.gl.createProgram();
    this.gl.attachShader(program, vertex);
    this.gl.attachShader(program, fragment);
    this.gl.linkProgram(program);
    return program;
  }

  setState(value) {
    const modes = { idle: 0, monitoring: 0.32, armed: 0.92, follow_up: 0.7, listening: 1, speech_detected: 1.35, transcribing: 1.85, thinking: 2.2, speaking: 3, error: 4, interrupted: 0.45 };
    this.targetMode = modes[value] ?? 0;
  }

  setLevel(value) {
    const level = Math.max(0, Math.min(1, Number(value) || 0));
    this.targetLevel = Math.max(this.targetLevel, level);
    this.impulse = Math.max(this.impulse, level);
  }

  resize() {
    const size = Math.max(1, this.canvas.clientWidth);
    const scale = window.devicePixelRatio || 1;
    const pixels = Math.floor(size * scale);
    if (this.canvas.width !== pixels || this.canvas.height !== pixels) {
      this.canvas.width = pixels;
      this.canvas.height = pixels;
    }
    this.gl.viewport(0, 0, pixels, pixels);
  }

  render(now) {
    if (!this.gl) {
      return;
    }
    this.resize();
    const stateRate = Math.abs(this.targetMode - this.mode) > 1.3 ? 0.045 : 0.065;
    this.mode += (this.targetMode - this.mode) * stateRate;
    const attack = this.targetLevel > this.level ? 0.3 : 0.055;
    this.level += (this.targetLevel - this.level) * attack;
    this.targetLevel *= 0.91;
    this.impulse *= 0.9;
    const displayedLevel = Math.min(1, this.level + this.impulse * 0.18);
    this.gl.useProgram(this.program);
    this.gl.bindBuffer(this.gl.ARRAY_BUFFER, this.buffer);
    this.gl.enableVertexAttribArray(this.position);
    this.gl.vertexAttribPointer(this.position, 2, this.gl.FLOAT, false, 0, 0);
    this.gl.uniform1f(this.time, (now - this.startedAt) / 1000);
    this.gl.uniform2f(this.resolution, this.canvas.width, this.canvas.height);
    this.gl.uniform1f(this.audio, displayedLevel);
    this.gl.uniform1f(this.state, this.mode);
    this.gl.clearColor(0, 0, 0, 0);
    this.gl.clear(this.gl.COLOR_BUFFER_BIT);
    this.gl.drawArrays(this.gl.TRIANGLE_STRIP, 0, 4);
    requestAnimationFrame(this.render);
  }
}
