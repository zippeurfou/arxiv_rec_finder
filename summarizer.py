import logging
from ollama import Client

def summarize_with_ollama(title, abstract):
    """
    Summarize a paper using the Ollama LLM.
    Args:
        title (str): The title of the paper.
        abstract (str): The abstract of the paper.
    Returns:
        str: A summary of the paper in 3 sentences.
    """
    prompt = f"Summarize this paper in 3 sentences:\nTitle: {title}\nAbstract: {abstract}"
    try:
        client = Client()
        response = client.chat(model="deepseek-r1:latest",
                               think=True,
                               messages=[{"role": "user", "content": prompt}])
        return response["message"]["content"].strip()
    except Exception as e:
        logging.warning(f"Ollama error: {e}")
        return f"(Abstract fallback)\n\n{abstract[:500]}..."

