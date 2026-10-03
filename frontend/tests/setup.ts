import { beforeEach, afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

beforeEach(() => localStorage.clear());
afterEach(cleanup);
