import React from 'react';
import { describe, expect, it } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import KatherineFace from '../src/features/katherine-face/KatherineFace.jsx';

// Exercise the real SVG renderer, not a replacement face component.
describe('Katherine presence activity', () => {
    it('projects confirmed loading into one decorative activity signal without replacing the face', () => {
        const { rerender } = render(<KatherineFace isLoading={false} />);
        const presence = screen.getByTestId('katherine-face');
        const head = presence.querySelector('.bwf-head');
        const eyes = [...presence.querySelectorAll('.bwf-eye')];
        const arc = screen.getByTestId('katherine-activity-arc');

        expect(head).not.toBeNull();
        expect(eyes).toHaveLength(2);
        expect(presence).toHaveAttribute('data-activity', 'idle');
        expect(arc).toHaveAttribute('aria-hidden', 'true');
        expect(arc).toHaveAttribute('focusable', 'false');
        expect(arc.querySelectorAll('path')).toHaveLength(1);
        expect(arc.querySelector('animate, animateTransform')).toBeNull();
        expect(screen.queryByRole('progressbar')).toBeNull();

        rerender(<KatherineFace isLoading />);
        expect(presence).toHaveAttribute('data-activity', 'busy');
        expect(presence.querySelector('.bwf-head')).toBe(head);
        expect([...presence.querySelectorAll('.bwf-eye')]).toEqual(eyes);
        expect(screen.getAllByTestId('katherine-activity-arc')).toHaveLength(1);

        rerender(<KatherineFace isLoading={false} />);
        expect(presence).toHaveAttribute('data-activity', 'idle');
        expect(presence.querySelector('.bwf-head')).toBe(head);
    });

    it.each([undefined, null, 0, 1, 'true', {}, []])('does not infer activity from unconfirmed loading: %s', (isLoading) => {
        render(<KatherineFace isLoading={isLoading} />);
        expect(screen.getByTestId('katherine-face')).toHaveAttribute('data-activity', 'idle');
    });

    it('isolates simultaneous face instances and removes their signals on unmount', () => {
        const first = render(<KatherineFace isLoading />);
        const second = render(<KatherineFace isLoading={false} />);
        const faces = screen.getAllByTestId('katherine-face');
        expect(faces[0]).toHaveAttribute('data-activity', 'busy');
        expect(faces[1]).toHaveAttribute('data-activity', 'idle');
        first.unmount();
        expect(screen.getAllByTestId('katherine-activity-arc')).toHaveLength(1);
        expect(screen.getByTestId('katherine-face')).toHaveAttribute('data-activity', 'idle');
        second.unmount();
        expect(screen.queryByTestId('katherine-activity-arc')).toBeNull();
    });
});
