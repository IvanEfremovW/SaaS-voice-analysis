import type { DataProvider } from '#backend/infrastructure/data-provider.ts';
import type { CallStatus } from './entity.ts';
import type { ProviderCall, ProviderCallFilter, ProviderFile, ProviderTranscription } from './types.ts';

/** The routes of data_provider for calls, their files and transcriptions. */
export class CallClient {
  #dataProvider: DataProvider;

  constructor(dataProvider: DataProvider) {
    this.#dataProvider = dataProvider;
  }

  async list(filter: ProviderCallFilter): Promise<ProviderCall[]> {
    return (await this.#dataProvider.get<{ calls: ProviderCall[] }>('/calls', filter)).calls;
  }

  async get(id: string): Promise<ProviderCall> {
    return (await this.#dataProvider.get<{ call: ProviderCall }>(`/calls/${encodeURIComponent(id)}`)).call;
  }

  async setStatus(callId: string, value: CallStatus): Promise<void> {
    await this.#dataProvider.send('PATCH', `/calls/${encodeURIComponent(callId)}/status`, { value });
  }

  async getFile(id: string): Promise<ProviderFile> {
    return (await this.#dataProvider.get<{ file: ProviderFile }>(`/files/${encodeURIComponent(id)}`)).file;
  }

  /** The file content, with its name in Content-Disposition. */
  async downloadFile(id: string): Promise<Response> {
    return this.#dataProvider.request('GET', `/files/${encodeURIComponent(id)}/content`);
  }

  /** Null if the call has no transcription. */
  async findTranscription(callId: string): Promise<ProviderTranscription | null> {
    const { transcriptions } = await this.#dataProvider.get<{ transcriptions: ProviderTranscription[] }>('/transcriptions', {
      callId,
    });
    return transcriptions[0] ?? null;
  }

  /** Deletes the transcription with its file. */
  async deleteTranscription(id: string): Promise<void> {
    await this.#dataProvider.send('DELETE', `/transcriptions/${encodeURIComponent(id)}`);
  }
}
