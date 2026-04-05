import type { PressableStateCallbackType } from 'react-native';

type HoverablePressableState = PressableStateCallbackType & {
  hovered?: boolean;
};

export function getHoverState(state: PressableStateCallbackType): boolean {
  return Boolean((state as HoverablePressableState).hovered);
}
