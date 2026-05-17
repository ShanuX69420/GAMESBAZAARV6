import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = join(dirname(fileURLToPath(import.meta.url)), '..');

function readProjectFile(relativePath) {
  return readFileSync(join(rootDir, relativePath), 'utf8');
}

function pngDimensions(relativePath) {
  const bytes = readFileSync(join(rootDir, relativePath));
  expect(bytes.toString('ascii', 1, 4)).toBe('PNG');
  return {
    width: bytes.readUInt32BE(16),
    height: bytes.readUInt32BE(20),
  };
}

describe('PWA assets', () => {
  it('declares an installable manifest with generated icon assets', () => {
    const manifest = JSON.parse(readProjectFile('public/manifest.json'));
    const expectedSizes = [72, 96, 128, 144, 152, 192, 384, 512];

    expect(manifest.name).toBe('GamesBazaar');
    expect(manifest.short_name).toBe('GamesBazaar');
    expect(manifest.start_url).toBe('/');
    expect(manifest.scope).toBe('/');
    expect(manifest.display).toBe('standalone');
    expect(manifest.theme_color).toBe('#22c55e');
    expect(manifest.background_color).toBe('#0a0e17');
    expect(manifest.icons.map((icon) => icon.sizes)).toEqual(
      expectedSizes.map((size) => `${size}x${size}`)
    );

    for (const size of expectedSizes) {
      const iconPath = `public/icons/icon-${size}x${size}.png`;
      expect(existsSync(join(rootDir, iconPath))).toBe(true);
      expect(pngDimensions(iconPath)).toEqual({ width: size, height: size });
    }

    expect(
      manifest.icons
        .filter((icon) => icon.purpose?.includes('maskable'))
        .map((icon) => icon.sizes)
    ).toEqual(['192x192', '512x512']);
  });

  it('exposes manifest and apple touch icon metadata from the root layout', () => {
    const layoutSource = readProjectFile('app/layout.js');

    expect(layoutSource).toContain("manifest: '/manifest.json'");
    expect(layoutSource).toContain("apple: '/apple-touch-icon.png'");
    expect(layoutSource).toContain('appleWebApp');
    expect(pngDimensions('public/apple-touch-icon.png')).toEqual({
      width: 180,
      height: 180,
    });
  });
});
