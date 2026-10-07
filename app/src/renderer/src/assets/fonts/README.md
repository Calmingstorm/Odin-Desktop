# Bundled fonts

The renderer's content security policy allows only `font-src 'self'`, so the app ships its fonts. Each is licensed
under the SIL Open Font License 1.1; its licence text, with the copyright line, is next to the font files and is
copied into the packaged app's `legal/fonts/` folder.

| Font | Files | Source | Licence |
|---|---|---|---|
| Bricolage Grotesque (weight and optical size axes) | `bricolage-grotesque-latin{,-ext}-opsz-normal.woff2` | npm `@fontsource-variable/bricolage-grotesque@5.3.0` (Google Fonts v9) | `OFL-BricolageGrotesque.txt` |
| Figtree (weight axis, upright and italic) | `figtree-latin{,-ext}-wght-{normal,italic}.woff2` | npm `@fontsource-variable/figtree@5.3.0` | `OFL-Figtree.txt` |
| JetBrains Mono (weight axis) | `jetbrains-mono-latin{,-ext}-wght-normal.woff2` | npm `@fontsource-variable/jetbrains-mono@5.3.0` | `OFL-JetBrainsMono.txt` |

Package tarball SHA-256:
- `fontsource-variable-bricolage-grotesque-5.3.0.tgz`: `6e99e0d844f7bc152bb3b007f9b1493c53e60cc0744cc681bb744e0b5f14665e`
- `fontsource-variable-figtree-5.3.0.tgz`: `745eb850be26774948b5aa9342b7182660ed3a48ac40509c7babcfdcd90c39d7`
- `fontsource-variable-jetbrains-mono-5.3.0.tgz`: `996fe6368a480c9ce15d4de22a2682b7c40b403718fee2b15e7272f244fd993f`

The files are unmodified copies of the packages' Latin and Latin Extended subsets. Other scripts fall back to the
system font.
