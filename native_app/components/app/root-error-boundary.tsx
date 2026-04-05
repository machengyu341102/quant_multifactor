import { Component, type ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

interface RootErrorBoundaryProps {
  children: ReactNode;
}

interface RootErrorBoundaryState {
  errorMessage: string | null;
}

export class RootErrorBoundary extends Component<
  RootErrorBoundaryProps,
  RootErrorBoundaryState
> {
  state: RootErrorBoundaryState = {
    errorMessage: null,
  };

  static getDerivedStateFromError(error: unknown): RootErrorBoundaryState {
    return {
      errorMessage: error instanceof Error ? error.message : '应用启动失败',
    };
  }

  componentDidCatch(error: unknown) {
    console.error('alphaai.root_error', error);
  }

  render() {
    if (!this.state.errorMessage) {
      return this.props.children;
    }

    return (
      <View style={styles.container}>
        <View style={styles.card}>
          <Text style={styles.title}>应用启动失败</Text>
          <Text style={styles.body}>{this.state.errorMessage}</Text>
          <Pressable
            onPress={() => {
              this.setState({ errorMessage: null });
            }}
            style={styles.button}>
            <Text style={styles.buttonText}>重新打开</Text>
          </Pressable>
        </View>
      </View>
    );
  }
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#EEF6F0',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 20,
  },
  card: {
    width: '100%',
    maxWidth: 420,
    backgroundColor: '#FFFFFF',
    borderRadius: 24,
    padding: 20,
    gap: 12,
  },
  title: {
    color: '#102017',
    fontSize: 18,
    fontWeight: '800',
  },
  body: {
    color: '#5A6D61',
    fontSize: 14,
    lineHeight: 20,
  },
  button: {
    marginTop: 4,
    minHeight: 44,
    borderRadius: 14,
    backgroundColor: '#14804A',
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '800',
  },
});
