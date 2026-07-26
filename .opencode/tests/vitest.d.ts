declare module "vitest" {
  export function describe(name: string, fn: () => void): void;
  export function it(name: string, fn: () => void | Promise<void>): void;
  export function expect<T>(actual: T): {
    toBe(expected: T): void;
    toEqual(expected: unknown): void;
    toHaveLength(expected: number): void;
    toContain(expected: unknown): void;
    toMatchObject(expected: Record<string, unknown>): void;
    not: {
      toContain(expected: unknown): void;
    };
    toBeNull(): void;
    readonly [key: number]: {
      toMatchObject(expected: Record<string, unknown>): void;
      toBe(expected: unknown): void;
      toEqual(expected: unknown): void;
      readonly severity: string;
      readonly line: number;
      readonly added: readonly string[];
      readonly removed: readonly string[];
    };
  };
}

