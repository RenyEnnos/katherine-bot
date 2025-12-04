import React from 'react';
import { Heart, Zap, Crown } from 'lucide-react';
import { toPercent } from '../../../shared/utils/formatters';

const EmotionPanel = ({ emotionState }) => {
    if (!emotionState) return null;

    const { pleasure, arousal, dominance, mood_label, acting_instruction } = emotionState;

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
                        <div className="w-full bg-gray-700 rounded-full h-1.5">
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
