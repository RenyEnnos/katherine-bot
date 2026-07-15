import React from 'react';
import { Heart, Zap, Crown } from 'lucide-react';
import {
    bipolarToPercent,
    intensityToPercent,
    getEmotionLabel,
} from '../../../shared/utils/formatters';

const PAD_CONFIG = [
    { label: 'Prazer', key: 'pleasure', icon: Heart, color: 'bg-pink-500' },
    { label: 'Energia', key: 'arousal', icon: Zap, color: 'bg-yellow-500' },
    { label: 'Dominância', key: 'dominance', icon: Crown, color: 'bg-purple-500' },
];

const EmotionPanel = ({ emotionState }) => {
    if (!emotionState) return null;

    const { pad, mood_label, dominant_emotions } = emotionState;
    if (!pad) return null;

    return (
        <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 shadow-lg w-full md:w-72 mt-4 md:mt-0 md:ml-4 flex-shrink-0">
            <h3 className="text-gray-400 text-xs font-bold uppercase tracking-wider mb-3">
                Humor da Katherine agora
            </h3>

            <div className="mb-4">
                <div className="text-xl font-semibold text-white mb-1">{mood_label}</div>
            </div>

            {/* Discrete Emotions */}
            {dominant_emotions && dominant_emotions.length > 0 && (
                <div className="mb-4 flex flex-wrap gap-2">
                    {dominant_emotions.map((emotion) => {
                        const displayLabel = getEmotionLabel(emotion.name);
                        const pct = intensityToPercent(emotion.intensity);
                        return (
                            <span
                                key={emotion.name}
                                className="text-xs font-medium px-2 py-1 rounded-full bg-gray-700 text-gray-200"
                            >
                                {displayLabel} {pct}%
                            </span>
                        );
                    })}
                </div>
            )}

            <div className="space-y-3">
                {PAD_CONFIG.map(({ label, key, icon: Icon, color }) => {
                    const value = pad[key];
                    const percentage = bipolarToPercent(value);
                    const labelId = `emotion-label-${label}`;

                    return (
                        <div key={label}>
                            <div className="flex justify-between text-xs text-gray-400 mb-1">
                                <span id={labelId} className="flex items-center gap-1">
                                    <Icon size={12} /> {label}
                                </span>
                                <span aria-hidden="true">{percentage}%</span>
                            </div>
                            <div
                                className="w-full bg-gray-700 rounded-full h-1.5"
                                role="progressbar"
                                aria-labelledby={labelId}
                                aria-valuenow={percentage}
                                aria-valuemin="0"
                                aria-valuemax="100"
                            >
                                <div
                                    className={`${color} h-1.5 rounded-full transition-all duration-500 ease-out`}
                                    style={{ width: `${percentage}%` }}
                                ></div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export default EmotionPanel;
