# Design System — Quick Reference

## Font Pairings Aprovados

### 1. Tech/Startup
- Display: Space Grotesk 800
- Body: IBM Plex Sans 400
- Load: `family=Space+Grotesk:wght@400;700;800&family=IBM+Plex+Sans:wght@300;400;500;600`

### 2. Premium/Luxo
- Display: Playfair Display 800
- Body: Satoshi 400
- Load: `family=Playfair+Display:wght@400;700;800&family=Satoshi:wght@300;400;500;700`

### 3. Moderno/Bold
- Display: Bricolage Grotesque 800
- Body: DM Sans 400
- Load: `family=Bricolage+Grotesque:wght@200;400;800&family=DM+Sans:wght@300;400;500;700`

### 4. Editorial/Elegante
- Display: Fraunces 800
- Body: Crimson Pro 400
- Load: `family=Fraunces:wght@200;400;800&family=Crimson+Pro:wght@300;400;600`

### 5. Clean/Geometric
- Display: Cabinet Grotesk 800
- Body: Source Sans 3 400
- Load: `family=Cabinet+Grotesk:wght@400;700;800&family=Source+Sans+3:wght@300;400;600`

## Background Snippets

### Dark com dot grid
```css
background: #0a0a12;
background-image: radial-gradient(rgba(255,255,255,.03) 1px, transparent 1px);
background-size: 24px 24px;
```

### Dark com glow
```css
background: #0a0a12;
background-image: radial-gradient(ellipse at 50% 0%, rgba(124,92,252,.06) 0%, transparent 50%);
```

### Light editorial
```css
background: #FAFAF8;
background-image: linear-gradient(rgba(0,0,0,.02) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,.02) 1px, transparent 1px);
background-size: 40px 40px;
```

### Warm gradient
```css
background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
```

## Animacao Snippets

### Staggered reveal
```css
.item { opacity: 0; animation: fadeUp .5s ease-out forwards; }
.item:nth-child(1) { animation-delay: .1s; }
.item:nth-child(2) { animation-delay: .2s; }
.item:nth-child(3) { animation-delay: .3s; }
@keyframes fadeUp { from{opacity:0;transform:translateY(16px)} to{opacity:1;transform:translateY(0)} }
```

### Card hover glow
```css
.card { transition: all .25s ease; }
.card:hover { transform: translateY(-4px); box-shadow: 0 8px 30px rgba(124,92,252,.15); border-color: var(--primary); }
```

### Scroll reveal
```css
.reveal { opacity: 0; transform: translateY(20px); transition: all .6s ease; }
.reveal.visible { opacity: 1; transform: translateY(0); }
```

## Paletas por Nicho

### Barbearia: dark, masculine
- Primary: #D4A574 (bronze), Accent: #2C2C2C, Bg: #1A1A1A, Text: #F5F0EB

### Restaurante: warm, appetizing
- Primary: #E85D04 (laranja), Accent: #370617, Bg: #FFFBF5, Text: #2B2D42

### Saude/Clinica: clean, trustworthy
- Primary: #0EA5E9 (azul sky), Accent: #065F46, Bg: #F0FDFA, Text: #1E293B

### Tech/SaaS: modern, bold
- Primary: #8B5CF6 (roxo), Accent: #06B6D4, Bg: #0F172A, Text: #F8FAFC

### Moda: elegant, editorial
- Primary: #000000, Accent: #B8860B, Bg: #FFFFFF, Text: #1A1A1A

### Fitness: energetic, strong
- Primary: #EF4444 (vermelho), Accent: #FCD34D, Bg: #18181B, Text: #FAFAFA

### Educacao: friendly, accessible
- Primary: #2563EB (azul), Accent: #F59E0B, Bg: #FFFDF7, Text: #1E3A5F
