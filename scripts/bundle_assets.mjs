import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import esbuild from 'esbuild';
import { createHash } from 'node:crypto';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

const nodeModulesDir = path.join(rootDir, 'node_modules');
const staticDir = path.join(rootDir, 'src', 'static');
const vendorDir = path.join(staticDir, 'vendor');

async function bundle() {
  console.log('Building local SBB assets for offline & packaging support...');

  // 1. Verify node_modules
  if (!fs.existsSync(nodeModulesDir)) {
    console.error('node_modules directory not found. Please run "npm install" first.');
    process.exit(1);
  }

  // 2. Ensure target directories exist
  fs.mkdirSync(vendorDir, { recursive: true });

  // 3. Bundle SBB Web Components with esbuild
  const entryCode = `
    import '@sbb-esta/lyne-elements/container.js';
    import '@sbb-esta/lyne-elements/button.js';
    import '@sbb-esta/lyne-elements/card.js';
    import '@sbb-esta/lyne-elements/dialog.js';
    import '@sbb-esta/lyne-elements/form-field.js';
    import '@sbb-esta/lyne-elements/header.js';
    import '@sbb-esta/lyne-elements/image.js';
    import '@sbb-esta/lyne-elements/signet.js';
    import '@sbb-esta/lyne-elements/logo.js';
    import '@sbb-esta/lyne-elements/title.js';
    import '@sbb-esta/lyne-elements/chip-label.js';
    import '@sbb-esta/lyne-elements/clock.js';
    import '@sbb-esta/lyne-elements/icon.js';
    import '@sbb-esta/lyne-elements/checkbox.js';
    import '@sbb-esta/lyne-elements/checkbox-group.js';
    import '@sbb-esta/lyne-elements/radio-button.js';
    import '@sbb-esta/lyne-elements/radio-button-group.js';
    import '@sbb-esta/lyne-elements/option.js';
    import '@sbb-esta/lyne-elements/select.js';
    import '@sbb-esta/lyne-elements/divider.js';
    import '@sbb-esta/lyne-elements/link.js';
    import '@sbb-esta/lyne-elements/menu.js';
    import '@sbb-esta/lyne-elements/notification.js';
    import '@sbb-esta/lyne-elements/carousel.js';
  `;

  console.log('  → Bundling SBB Elements into vendor/sbb-elements.bundle.js...');
  await esbuild.build({
    stdin: {
      contents: entryCode,
      resolveDir: rootDir,
      loader: 'js',
    },
    bundle: true,
    minify: true,
    format: 'esm',
    outfile: path.join(vendorDir, 'sbb-elements.bundle.js'),
    logLevel: 'info',
  });

  // 4. Copy CSS files
  console.log('  → Copying SBB design token & theme CSS...');
  const varsCssSrc = path.join(nodeModulesDir, '@sbb-esta', 'lyne-design-tokens', 'dist', 'css', 'sbb-variables.css');
  const themeCssSrc = path.join(nodeModulesDir, '@sbb-esta', 'lyne-elements', 'standard-theme.css');

  fs.copyFileSync(varsCssSrc, path.join(vendorDir, 'sbb-variables.css'));
  fs.copyFileSync(themeCssSrc, path.join(vendorDir, 'standard-theme.css'));

  // The Python loader rejects old or incomplete bundles rather than leaving
  // pages waiting forever for custom elements that were never registered.
  const packageVersion = (name) => JSON.parse(fs.readFileSync(
    path.join(nodeModulesDir, '@sbb-esta', name, 'package.json'), 'utf8',
  )).version;
  const manifest = {
    elements_version: packageVersion('lyne-elements'),
    tokens_version: packageVersion('lyne-design-tokens'),
    components: [...entryCode.matchAll(/lyne-elements\/([^']+)\.js/g)].map(match => match[1]),
    bundle_sha256: createHash('sha256').update(
      fs.readFileSync(path.join(vendorDir, 'sbb-elements.bundle.js')),
    ).digest('hex'),
  };
  fs.writeFileSync(path.join(vendorDir, 'manifest.json'), JSON.stringify(manifest, null, 2));

  console.log('✓ Successfully generated local SBB assets in src/static/vendor!');
}

bundle().catch((err) => {
  console.error('Bundle error:', err);
  process.exit(1);
});
