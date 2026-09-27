import { Config } from '@remotion/cli/config';

// Preserve fine UI strokes before the final video encode.
Config.setVideoImageFormat('png');
Config.setColorSpace('bt709');
Config.setOverwriteOutput(true);
