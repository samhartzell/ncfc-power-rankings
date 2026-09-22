/* Crest drawing and the team tint, shared by both pages. Inlined into every
   template at build time so each page still ships as a single file. */
  /* ---------- crests ----------
     A shield in the club's kit colors, with the pattern those colors go in and
     a name band across the front. Drawn here rather than shipped as artwork:
     nothing is copied from a club. */

  const SVG_NS = "http://www.w3.org/2000/svg";
  const SHIELD = "M8 5 H92 V57 C92 83 74 100 50 107 C26 100 8 83 8 57 Z";
  let crestSeq = 0;

  const svg = (tag, attrs) => {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
    return node;
  };

  const box = (x, y, w, h, fill) => svg("rect", { x, y, width: w, height: h, fill });

  function luminance(hex) {
    const h = hex.replace("#", "");
    const parts = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
    const lin = parts.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
  }

  function patternShapes(group, pattern, field, trim, accent) {
    switch (pattern) {
      case "stripes":
        for (let x = 8; x < 100; x += 28) group.append(box(x, 0, 14, 112, trim));
        break;
      case "hoops":
        for (let y = 8; y < 112; y += 30) group.append(box(0, y, 100, 15, trim));
        break;
      case "halves":
        group.append(box(50, 0, 50, 112, trim));
        break;
      case "diagonal":
        group.append(svg("polygon", { points: "100,0 100,112 0,112", fill: trim }));
        break;
      case "sash":
        group.append(svg("polygon", { points: "0,112 0,74 78,0 100,0 100,26 24,112", fill: trim }));
        break;
      case "sleeves":
        group.append(box(0, 0, 21, 112, trim));
        group.append(box(79, 0, 21, 112, trim));
        break;
      case "cross":
        group.append(box(38, 0, 24, 112, trim));
        group.append(box(0, 32, 100, 24, trim));
        if (accent) group.append(box(44, 0, 12, 112, accent));
        break;
      case "band":
        group.append(box(0, 40, 100, 26, trim));
        break;
      default:
        break;
    }
  }

  function crest(team, size) {
    const id = team.identity;
    const [field, trim, accent] = id.colors;
    const uid = `crest-${++crestSeq}`;
    const root = svg("svg", {
      class: "crest",
      viewBox: "0 0 100 112",
      width: size,
      height: Math.round(size * 1.12),
      role: "img",
      "aria-hidden": "true",
    });

    const defs = svg("defs");
    const clip = svg("clipPath", { id: uid });
    clip.append(svg("path", { d: SHIELD }));
    defs.append(clip);
    root.append(defs);

    const group = svg("g", { "clip-path": `url(#${uid})` });
    group.append(box(0, 0, 100, 112, field));
    patternShapes(group, id.pattern, field, trim, accent);

    // The name band, with the club's letters on it. Below about 26px the
    // letters stop being letters, so the crest is left as pure kit.
    if (size >= 26) {
      const sorted = [...id.colors].sort((a, b) => luminance(b) - luminance(a));
      const band = luminance(sorted[0]) > 0.55 ? sorted[0] : "#FFFFFF";
      const letters = luminance(sorted[sorted.length - 1]) < 0.5
        ? sorted[sorted.length - 1]
        : "#151A20";
      group.append(svg("rect", {
        x: 0, y: 50, width: 100, height: 26, fill: band,
        stroke: letters, "stroke-width": 1.5, "stroke-opacity": 0.35,
      }));
      const text = svg("text", {
        x: 50, y: 70, "text-anchor": "middle", fill: letters,
        "font-family": "IBM Plex Mono, ui-monospace, monospace",
        "font-size": id.code.length > 3 ? 18 : 22,
        "font-weight": 600,
        "letter-spacing": 0.5,
      });
      text.textContent = id.code;
      group.append(text);
    }

    root.append(group);
    root.append(svg("path", {
      d: SHIELD, fill: "none", stroke: "currentColor",
      "stroke-opacity": 0.28, "stroke-width": 4,
    }));
    return root;
  }

  function tint(node, team) {
    node.classList.add("tinted");
    node.style.setProperty("--team-l", team.identity.accent.light);
    node.style.setProperty("--team-d", team.identity.accent.dark);
    return node;
  }

  function tags(team) {
    const out = [];
    if (!team.host && team.org) out.push(team.org);
    if (team.site) out.push(team.site);
    return out;
  }
