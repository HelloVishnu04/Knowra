import React from 'react';
import {registerRoot, Composition} from 'remotion';
import {KivoPromo} from './KivoPromo';
const Root = () => <><style>{`*{box-sizing:border-box}body{margin:0}`}</style><Composition id="KivoAI" component={KivoPromo} width={1920} height={1080} fps={30} durationInFrames={900}/></>;
registerRoot(Root);
