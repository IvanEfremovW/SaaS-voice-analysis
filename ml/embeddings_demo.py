import numpy as np
from embeddings import get_embeddings


def cosine(a, b): #функция косинусного сходствa
    a = np.array(a)
    b = np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


texts = [
    "Сотрудник должен поздороваться и представиться в начале звонка",
    "В начале разговора менеджер обязан назвать себя и компанию",
    "Цена продукта начинается от 9900 рублей с учётом акции",
]

emb = get_embeddings()
vectors = emb.embed_documents(texts)

print("размерность вектора:", len(vectors[0]))
print("sim(приветствие, приветствие-синоним):", round(cosine(vectors[0], vectors[1]), 3))
print("sim(приветствие, цена):              ", round(cosine(vectors[0], vectors[2]), 3))
