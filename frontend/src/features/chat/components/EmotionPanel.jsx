import React from 'react';
import { Heart, Zap, Crown } from 'lucide-react';
import { toPercent } from '../../../shared/utils/formatters';

const EmotionPanel = ({ emotionState }) => {
    if (!emotionState) return null;

    const { pleasure, arousal, dominance, mood_label, acting_instruction, joy, sadness, anger, fear, disgust, surprise, guilt, pride, tenderness, jealousy, gratitude } = emotionState;

    const discreteEmotions = [
        { label: 'Alegria', value: joy, color: 'text-yellow-400' },
        { label: 'Tristeza', value: sadness, color: 'text-blue-400' },
        { label: 'Raiva', value: anger, color: 'text-red-500' },
        { label: 'Medo', value: fear, color: 'text-purple-400' },
        { label: 'Nojo', value: disgust, color: 'text-green-400' },
        { label: 'Surpresa', value: surprise, color: 'text-orange-400' },
        { label: 'Culpa', value: guilt, color: 'text-gray-400' },
        { label: 'Orgulho', value: pride, color: 'text-yellow-600' },
        { label: 'Ternura', value: tenderness, color: 'text-pink-300' },
        { label: 'Ciúmes', value: jealousy, color: 'text-green-600' },
        { label: 'Gratidão', value: gratitude, color: 'text-pink-500' },
    ].filter(e => e.value > 0.1).sort((a, b) => b.value - a.value).slice(0, 3);

    return (
        <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 shadow-lg w-full md:w-72 mt-4 md:mt-0 md:ml-4 flex-shrink-0">
            <h3 className="text-gray-400 text-xs font-bold uppercase tracking-wider mb-3">
                Humor da Katherine agora
            </h3>

            <div className="mb-4">
                <div className="text-xl font-semibold text-white mb-1">{mood_label}</div>
                <div className="text-gray-400 text-xs italic leading-tight">
                    "{acting_instruction}"
                </div>
            </div>

            {/* Discrete Emotions */}
            {discreteEmotions.length > 0 && (
                <div className="mb-4 flex flex-wrap gap-2">
                    {discreteEmotions.map(e => (
                        <span key={e.label} className={`text-xs font-medium px-2 py-1 rounded-full bg-gray-700 ${e.color}`}>
                            {e.label} {Math.round(e.value * 100)}%
                        </span>
                    ))}
                </div>
            )}

            <div className="space-y-3">
                {[
                    { label: 'Prazer', value: pleasure, icon: Heart, color: 'bg-pink-500' },
                    { label: 'Energia', value: arousal, icon: Zap, color: 'bg-yellow-500' },
                    { label: 'Dominância', value: dominance, icon: Crown, color: 'bg-purple-500' }
                ].map(({ label, value, icon: Icon, color }) => (
                    <div key={label}>
                        <div className="flex justify-between text-xs text-gray-400 mb-1">
                            <span className="flex items-center gap-1"><Icon size={12} /> {label}</span>
                            <span>{toPercent(value)}%</span>
                        </div>
                        <div
                            role="progressbar"
                            aria-label={label}
                            aria-valuenow={toPercent(value)}
                            aria-valuemin="0"
                            aria-valuemax="100"
                            className="w-full bg-gray-700 rounded-full h-1.5"
                        >
                            <div
                                className={`${color} h-1.5 rounded-full transition-all duration-500 ease-out`}
                                style={{ width: `${toPercent(value)}%` }}
                            ></div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default EmotionPanel;
