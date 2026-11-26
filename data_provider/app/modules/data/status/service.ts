import { database } from '#app/infrastructure/database.ts';
import { CALL_STATUSES, StatusError } from './entity.ts';
import type { CallStatus, Status, UpdateStatusInput } from './entity.ts';
import { StatusRepository } from './repository.ts';

export class StatusService {
  #statuses: StatusRepository;

  constructor(statuses: StatusRepository) {
    this.#statuses = statuses;
  }

  async create(value: CallStatus = 'UPLOADED'): Promise<Status> {
    return this.#statuses.create(checkValue(value));
  }

  async get(id: string): Promise<Status> {
    return (await this.#statuses.findById(id)) ?? notFound(id);
  }

  async list(value?: CallStatus): Promise<Status[]> {
    return this.#statuses.list(value === undefined ? undefined : checkValue(value));
  }

  async update(id: string, input: UpdateStatusInput): Promise<Status> {
    if (typeof input !== 'object' || input === null) throw new StatusError(400, 'Body must be a JSON object');
    const value = checkValue(input.value);

    let error: string | null = null;
    if (value === 'FAILED') {
      if (typeof input.error !== 'string' || !input.error.trim()) {
        throw new StatusError(400, '"error" must describe why processing FAILED');
      }
      error = input.error.trim();
    } else if (input.error !== undefined) {
      throw new StatusError(400, '"error" is only allowed with FAILED');
    }

    return (await this.#statuses.update(id, value, error)) ?? notFound(id);
  }

  async delete(id: string): Promise<void> {
    if (!(await this.#statuses.delete(id))) notFound(id);
  }
}

function checkValue(value: unknown): CallStatus {
  if (!CALL_STATUSES.includes(value as CallStatus)) {
    throw new StatusError(400, `"value" must be one of ${CALL_STATUSES.join(', ')}`);
  }
  return value as CallStatus;
}

function notFound(id: string): never {
  throw new StatusError(404, `Status ${id} not found`);
}

export const statusService = new StatusService(new StatusRepository(database));
