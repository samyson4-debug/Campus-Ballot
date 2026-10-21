/**
 * Campus Ballot — Login Page Animated Background
 * Elegant, interactive particle constellation network rendered on an HTML5 canvas.
 */

export function initCanvas(canvasId = 'bg-canvas') {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let width = 0;
    let height = 0;
    let animationFrameId = null;

    // Particle settings
    const PARTICLE_COUNT_DESKTOP = 65;
    const PARTICLE_COUNT_MOBILE = 35;
    const CONNECT_DISTANCE = 130;
    const MOUSE_RADIUS = 160;

    let particles = [];
    const mouse = { x: null, y: null, active: false };

    function resize() {
        width = canvas.width = window.innerWidth;
        height = canvas.height = window.innerHeight;
        initParticles();
    }

    class Particle {
        constructor() {
            this.x = Math.random() * width;
            this.y = Math.random() * height;
            this.vx = (Math.random() - 0.5) * 0.7;
            this.vy = (Math.random() - 0.5) * 0.7;
            this.radius = Math.random() * 2 + 1;
            // Palette matches CSS theme: indigo, light purple, subtle cyan
            const hue = Math.random() > 0.3 ? 240 + Math.random() * 20 : 180 + Math.random() * 30;
            this.color = `hsla(${hue}, 80%, 70%, 0.6)`;
        }

        update() {
            this.x += this.vx;
            this.y += this.vy;

            // Bounce off screen bounds
            if (this.x < 0 || this.x > width) this.vx *= -1;
            if (this.y < 0 || this.y > height) this.vy *= -1;

            // Gentle mouse reaction
            if (mouse.active && mouse.x !== null && mouse.y !== null) {
                const dx = mouse.x - this.x;
                const dy = mouse.y - this.y;
                const dist = Math.hypot(dx, dy);
                if (dist < MOUSE_RADIUS && dist > 0) {
                    const force = (MOUSE_RADIUS - dist) / MOUSE_RADIUS;
                    const angle = Math.atan2(dy, dx);
                    this.x -= Math.cos(angle) * force * 1.5;
                    this.y -= Math.sin(angle) * force * 1.5;
                }
            }
        }

        draw() {
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
            ctx.fillStyle = this.color;
            ctx.shadowBlur = 8;
            ctx.shadowColor = 'rgba(99, 102, 241, 0.4)';
            ctx.fill();
            ctx.shadowBlur = 0;
        }
    }

    function initParticles() {
        const count = width < 768 ? PARTICLE_COUNT_MOBILE : PARTICLE_COUNT_DESKTOP;
        particles = [];
        for (let i = 0; i < count; i++) {
            particles.push(new Particle());
        }
    }

    function animate() {
        ctx.clearRect(0, 0, width, height);

        // Draw connections
        for (let i = 0; i < particles.length; i++) {
            for (let j = i + 1; j < particles.length; j++) {
                const dx = particles[i].x - particles[j].x;
                const dy = particles[i].y - particles[j].y;
                const dist = Math.hypot(dx, dy);

                if (dist < CONNECT_DISTANCE) {
                    const alpha = (1 - dist / CONNECT_DISTANCE) * 0.25;
                    ctx.beginPath();
                    ctx.moveTo(particles[i].x, particles[i].y);
                    ctx.lineTo(particles[j].x, particles[j].y);
                    ctx.strokeStyle = `rgba(99, 102, 241, ${alpha})`;
                    ctx.lineWidth = 1;
                    ctx.stroke();
                }
            }
        }

        // Update and draw particles
        for (let i = 0; i < particles.length; i++) {
            particles[i].update();
            particles[i].draw();
        }

        animationFrameId = requestAnimationFrame(animate);
    }

    // Event listeners
    window.addEventListener('resize', resize);
    window.addEventListener('mousemove', (e) => {
        mouse.x = e.clientX;
        mouse.y = e.clientY;
        mouse.active = true;
    });
    window.addEventListener('mouseleave', () => {
        mouse.active = false;
    });

    resize();
    animate();

    return () => {
        if (animationFrameId) cancelAnimationFrame(animationFrameId);
        window.removeEventListener('resize', resize);
    };
}
