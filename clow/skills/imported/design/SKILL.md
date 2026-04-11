---
name: "design"
description: "Generate frontend designs: HTML/CSS/Tailwind landing pages, dashboards, UI components"
license: MIT
metadata:
  version: 1.0.0
  author: Clow
  category: business
---

# Design — Frontend Generation

Generate production-quality HTML/CSS designs. Every output must be a complete, working file.

## Stack
- **HTML5** semantic markup
- **Tailwind CSS** via CDN: `<script src="https://cdn.tailwindcss.com"></script>`
- **Google Fonts** for professional typography
- **Heroicons** or inline SVGs for icons
- No build tools required — single-file delivery

## Design Principles
1. **Visual hierarchy**: clear heading sizes, spacing, contrast
2. **Whitespace**: generous padding, do not crowd elements
3. **Color**: use a cohesive 3-color palette (primary, accent, neutral)
4. **Typography**: max 2 font families, clear size scale
5. **Mobile-first**: responsive by default, test at 375px and 1280px
6. **Accessibility**: proper contrast ratios, alt text, semantic HTML

## Page Templates

### Landing Page Structure
```
- Hero (headline + subheadline + CTA + visual)
- Social proof (logos, testimonials, numbers)
- Features/Benefits (3-4 key points with icons)
- How it works (3 steps)
- Pricing (if applicable)
- FAQ
- Final CTA
- Footer
```

### Dashboard Structure
```
- Sidebar navigation
- Top bar (search, user profile)
- KPI cards row
- Charts area (2-column grid)
- Data table with pagination
```

## Output Format
Always deliver as a single .html file:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Page Title</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
</head>
<body class="font-[Inter] bg-white text-gray-900">
    <!-- content -->
</body>
</html>
```

## Rules
- Every page must be responsive
- Use real-looking placeholder content, not "Lorem ipsum"
- Include hover states on interactive elements
- Use subtle animations (transitions) for polish
- Ensure all links and buttons are styled and clickable
- Save as .html file in the current directory
