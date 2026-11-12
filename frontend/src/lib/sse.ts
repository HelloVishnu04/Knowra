/** Buffers incomplete network frames, including split UTF-8 characters. */
export class ChatStreamDecoder {
  private buffer = '';
  private decoder = new TextDecoder();

  push(bytes: Uint8Array): string[] {
    this.buffer += this.decoder.decode(bytes, { stream: true });
    const lines = this.buffer.split('\n');
    this.buffer = lines.pop() || '';
    return lines.filter(line => line.startsWith('data: ')).map(line => line.slice(6).trim());
  }
}
