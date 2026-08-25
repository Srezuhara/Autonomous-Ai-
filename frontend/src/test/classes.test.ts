import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { globSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Every class the components reference must exist in a stylesheet.
 *
 * This exists because of a real regression: `.empty-state` was pruned from
 * globals.css during the surface-vocabulary collapse while `ProjectDetail`
 * still referenced it, so the "not found" state rendered completely unstyled.
 * Nothing failed — not the typecheck, not the build, not any component test,
 * because an unknown class is perfectly valid HTML.
 *
 * The first version of this check missed it, because the pruned name still
 * appeared inside a CSS *comment* explaining that it had been removed. Comments
 * are stripped before the selector set is built.
 */

const SRC = join(process.cwd(), 'src');

function read(pattern: string): string[] {
  return globSync(pattern, { cwd: SRC }).map(f => join(SRC, f));
}

/** Class names defined by any stylesheet, with comments removed first. */
function definedClasses(): Set<string> {
  const defined = new Set<string>();
  for (const file of read('**/*.css')) {
    const css = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
    for (const m of css.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)) defined.add(m[1]);
  }
  return defined;
}

/** Class names referenced by any component, keyed to the files using them. */
function usedClasses(): Map<string, Set<string>> {
  const used = new Map<string, Set<string>>();
  for (const file of read('**/*.tsx')) {
    if (file.endsWith('.test.tsx')) continue;
    const src = readFileSync(file, 'utf8');
    for (const m of src.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g)) {
      // Drop `${...}` interpolations — those halves are dynamic and get
      // covered by the component tests instead.
      const literal = (m[1] ?? m[2] ?? '').replace(/\$\{[^}]*\}/g, ' ');
      for (const cls of literal.split(/\s+/)) {
        if (!cls || cls.endsWith('--')) continue;
        if (!used.has(cls)) used.set(cls, new Set());
        used.get(cls)!.add(file.replace(SRC, 'src'));
      }
    }
  }
  return used;
}

/**
 * Block-level BEM hooks that intentionally carry no rules of their own — they
 * exist to namespace `__element` children. Anything not on this list that has
 * no rule is a dangling reference.
 */
const INTENTIONALLY_UNSTYLED = new Set(['proof']);

describe('CSS class references', () => {
  it('every class used in a component is defined in a stylesheet', () => {
    const defined = definedClasses();
    const dangling: string[] = [];

    for (const [cls, files] of usedClasses()) {
      if (defined.has(cls) || INTENTIONALLY_UNSTYLED.has(cls)) continue;
      dangling.push(`${cls}  ←  ${[...files].join(', ')}`);
    }

    expect(dangling).toEqual([]);
  });

  it('strips comments before collecting selectors', () => {
    // Guards the bug in this check's own first version: a class named only
    // inside a comment must not count as defined.
    const css = '/* .ghost-class was removed */ .real-class { color: red; }';
    const stripped = css.replace(/\/\*[\s\S]*?\*\//g, '');
    const found = [...stripped.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)].map(m => m[1]);
    expect(found).toEqual(['real-class']);
  });
});
