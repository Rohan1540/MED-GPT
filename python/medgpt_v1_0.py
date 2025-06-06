# -*- coding: utf-8 -*-
"""MEDGPT v1.0.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1DgfruqJIVRIhk92blBPbYEJ3lkvc1YrJ
"""

import pandas as pd
import sys
from src.logger import logging
from src.Exception import CustomException
import os
from datasets import load_dataset
from sentence_transformers import SentenceTransformer
import faiss
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from typing import List, Dict, Any, Union, Optional, Tuple
import numpy as np
import requests
from bs4 import BeautifulSoup
import re
import json
import time
from urllib.parse import quote_plus

class WebSearchEngine:
    """
    Simple web search engine that uses public APIs to search the web
    """
    def __init__(self, api_key=None):
        """
        Initialize the search engine

        Args:
            api_key: API key for search APIs (optional)
        """
        self.api_key = api_key
        # You would normally use a paid API like Bing or Google
        # For demonstration, we'll use SerpAPI or a basic fallback

    def search(self, query: str, num_results: int = 5) -> List[Dict[str, str]]:
        """
        Search the web for the given query

        Args:
            query: Search query
            num_results: Number of results to return

        Returns:
            List of search results with title, snippet, and URL
        """
        # First try using SerpAPI if API key is provided
        if self.api_key:
            try:
                return self._search_with_serpapi(query, num_results)
            except Exception as e:
                logging.error(f"SerpAPI search failed: {e}")

        # Fall back to a basic approach
        return self._search_with_ddg(query, num_results)

    def _search_with_serpapi(self, query: str, num_results: int) -> List[Dict[str, str]]:
        """Use SerpAPI to search"""
        params = {
            "q": query,
            "api_key": self.api_key,
            "num": num_results
        }
        response = requests.get("https://serpapi.com/search", params=params)
        data = response.json()

        results = []
        for item in data.get("organic_results", [])[:num_results]:
            results.append({
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "url": item.get("link", "")
            })
        return results

    def _search_with_ddg(self, query: str, num_results: int) -> List[Dict[str, str]]:
        """Use DuckDuckGo for basic search"""
        # Note: This is a basic implementation and might break with DDG changes
        # A more reliable solution would use a paid API
        encoded_query = quote_plus(query + " health medical")
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        try:
            response = requests.get(url, headers=headers)
            soup = BeautifulSoup(response.text, "html.parser")

            results = []
            for result in soup.select(".result")[:num_results]:
                title_elem = result.select_one(".result__a")
                snippet_elem = result.select_one(".result__snippet")

                title = title_elem.text if title_elem else ""
                snippet = snippet_elem.text if snippet_elem else ""
                url = title_elem.get("href", "") if title_elem else ""

                # Clean up the URL
                if url.startswith("/"):
                    url_match = re.search(r'uddg=([^&]+)', url)
                    if url_match:
                        url = requests.utils.unquote(url_match.group(1))

                results.append({
                    "title": title,
                    "snippet": snippet,
                    "url": url
                })

            return results
        except Exception as e:
            logging.error(f"DDG search failed: {e}")
            raise CustomException(e,sys)
            # Return empty results if search fails
            return []

    def fetch_content(self, url: str) -> str:
        """
        Fetch and extract meaningful content from a webpage

        Args:
            url: URL to fetch

        Returns:
            Extracted text content
        """
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.text, "html.parser")

            # Remove script and style elements
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.extract()

            # Get text
            text = soup.get_text(separator='\n')

            # Clean up text
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)

            # Truncate if too long
            if len(text) > 8000:
                text = text[:8000] + "..."

            return text
        except Exception as e:
            logging.error(f"Failed to fetch {url}: {e}")
            return ""


class HealthcareRAG:
    def __init__(self, model_name="microsoft/Phi-3.5-mini-instruct", cache_dir=None, device="cuda", search_api_key=None):
        """
        Initialize the Healthcare RAG system with Phi-3.5 model and web search capability

        Args:
            model_name: The Phi-3.5 model to use
            cache_dir: Directory to cache models
            device: Device to run the model on ('cuda' or 'cpu')
            search_api_key: API key for web search (optional)
        """
        try:
            self.device = "cuda" if torch.cuda.is_available() and device == "cuda" else "cpu"
            logging.info(f"Using device: {self.device}")

            # Load tokenizer and model
            logging.info("Loading Phi-3.5 model and tokenizer...")
            self.tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
            self.model = AutoModelForCausalLM.from_pretrained(
                model_name,
                torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
                cache_dir=cache_dir
            ).to(self.device)

            # Load embedding model
            logging.info("Loading embedding model...")
            self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2').to(self.device)

            # Initialize empty index and document store
            self.index = None
            self.documents = []

            # Initialize web search engine
            self.search_engine = WebSearchEngine(api_key=search_api_key)

            # Configure confidence threshold for local knowledge base
            self.confidence_threshold = 0.6  # Adjust based on your dataset

        except Exception as e:
            logging.error("Failed to initialize HealthcareRAG class")
            raise CustomException(e, sys)
    
    def load_healthcare_magic_dataset(self, limit=10000):
        try:
            """
            Load and prepare Healthcare Magic dataset

            Args:
                limit: Number of rows to use (default: 10000)
            """
            logging.info(f"Loading Healthcare Magic dataset (limit: {limit})...")
            dataset = load_dataset("lavita/ChatDoctor-HealthCareMagic-100k")

            # Get the 'train' split and convert to DataFrame
            df = dataset['train'].to_pandas()

            # Select just what we need and limit rows
            df = df.head(limit)

            # Process the dataset
            self.documents = []
            for idx, row in df.iterrows():
                # Combine question and answer into a document
                document = {
                    'id': idx,
                    'question': row['input'],
                    'answer': row['output'],
                    'content': f"Question: {row['input']}\nAnswer: {row['output']}"
                }
                self.documents.append(document)

            logging.info(f"Processed {len(self.documents)} documents from Healthcare Magic dataset")
        except Exception as e:
            logging.error("Failed to load Healthcare Magic dataset")
            raise CustomException(e, sys)

    def build_index(self):
        try:
            """
            Build FAISS index from documents
            """
            logging.info("Building search index...")

            # Create text chunks to embed
            texts = [doc['content'] for doc in self.documents]

            # Generate embeddings
            embeddings = self.embedding_model.encode(texts, show_progress_bar=True)

            # Normalize embeddings
            embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

            # Build FAISS index
            vector_dimension = embeddings.shape[1]
            self.index = faiss.IndexFlatIP(vector_dimension)
            self.index.add(embeddings.astype('float32'))

            logging.info(f"Index built with {self.index.ntotal} vectors of dimension {vector_dimension}")
        except Exception as e:
            logging.error("Failed to build FAISS index")
            raise CustomException(e, sys)
        
    def add_document_to_index(self, document: Dict[str, Any]):
        try:
            """
            Add a new document to the index and document store

            Args:
                document: Document to add
            """
            if not self.index:
                raise ValueError("Index not initialized. Call build_index first.")

            # Add to document store
            doc_id = len(self.documents)
            document['id'] = doc_id
            self.documents.append(document)

            # Add to index
            embedding = self.embedding_model.encode([document['content']], show_progress_bar=False)
            embedding = embedding / np.linalg.norm(embedding, axis=1, keepdims=True)
            self.index.add(embedding.astype('float32'))

            return doc_id
        except Exception as e:
            logging.error("Failed to add document to index")
            raise CustomException(e, sys)

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        try:
            """
            Retrieve relevant documents for a query

            Args:
                query: User query
                top_k: Number of documents to retrieve

            Returns:
                List of relevant documents
            """
            # Generate embedding for the query
            query_embedding = self.embedding_model.encode([query], show_progress_bar=False)
            query_embedding = query_embedding / np.linalg.norm(query_embedding)

            # Search the index
            scores, indices = self.index.search(query_embedding.astype('float32'), top_k)

            # Retrieve matching documents
            results = []
            for i, idx in enumerate(indices[0]):
                if idx != -1 and idx < len(self.documents):  # Valid index
                    doc = self.documents[idx]
                    results.append({
                        'id': doc['id'],
                        'content': doc['content'],
                        'question': doc['question'],
                        'answer': doc['answer'],
                        'score': float(scores[0][i]),
                        'source': 'local_database'
                    })

            return results
        except Exception as e:
            logging.error("Failed to retrieve documents")
            raise CustomException(e, sys)
        

    def search_web(self, query: str, num_results: int = 3) -> List[Dict[str, Any]]:
        try:
            """
            Search the web for relevant information

            Args:
                query: User query
                num_results: Number of web results to retrieve

            Returns:
                List of processed web documents
            """
            # Search the web
            search_results = self.search_engine.search(query, num_results)

            # Process results
            web_docs = []
            for i, result in enumerate(search_results):
                # Fetch the full content from the URL
                full_content = self.search_engine.fetch_content(result["url"])

                # Skip if content retrieval failed
                if not full_content:
                    continue

                # Create a document
                doc = {
                    'id': f"web_{i}",
                    'title': result["title"],
                    'snippet': result["snippet"],
                    'url': result["url"],
                    'content': full_content,
                    'score': 1.0 - (i * 0.1),  # Simple relevance score based on search ranking
                    'source': 'web'
                }
                web_docs.append(doc)

                # Optionally add to knowledge base for future use
                # Simplified content for embedding (title + snippet)
                simplified_content = f"Question: {query}\nAnswer: {result['title']}. {result['snippet']}"
                local_doc = {
                    'question': query,
                    'answer': f"{result['title']}. {result['snippet']}",
                    'content': simplified_content,
                    'url': result['url']
                }
                self.add_document_to_index(local_doc)

            return web_docs
        except Exception as e:
            logging.error("Failed to search the web")
            raise CustomException(e, sys)
    def generate_response(self, query: str, retrieved_docs: List[Dict[str, Any]]) -> Tuple[str, bool]:
        """
        Generate response using Phi-3.5 with retrieved context

        Args:
            query: User query
            retrieved_docs: Retrieved documents

        Returns:
            Tuple of (response text, whether web search was used)
        """
        # Check if we have sufficient confidence in local results
        local_docs = [doc for doc in retrieved_docs if doc.get('source') == 'local_database']
        web_docs = [doc for doc in retrieved_docs if doc.get('source') == 'web']

        used_web_search = len(web_docs) > 0

        # Sort all docs by relevance score
        sorted_docs = sorted(retrieved_docs, key=lambda x: x['score'], reverse=True)

        # Format context with relevance scores and sources
        context_parts = []
        for i, doc in enumerate(sorted_docs):
            if doc.get('source') == 'local_database':
                context_parts.append(
                    f"[Document {i+1}] Relevance: {doc['score']:.2f} Source: Database\n"
                    f"Q: {doc['question']}\nA: {doc['answer']}"
                )
            elif doc.get('source') == 'web':
                # For web sources, include URL and a snippet of content
                context_parts.append(
                    f"[Document {i+1}] Relevance: {doc['score']:.2f} Source: Web - {doc['url']}\n"
                    f"Title: {doc.get('title', '')}\n"
                    f"Content: {doc.get('snippet', '')}"
                )

        context = "\n\n".join(context_parts)

        # Create prompt based on source of information
        prompt = f"""You are a helpful healthcare assistant providing information based on medical knowledge.
Answer the user's health question using the information from the retrieved documents below.

Retrieved Documents:
{context}

User Question: {query}

Guidelines:
1. If the retrieved information doesn't contain a direct answer, say "I don't have enough information to answer this question confidently."
2. Be concise and focused on addressing the main concern.
3. Present symptoms, possible causes, and general treatments if available in the retrieved information.
4. Always include a medical disclaimer reminding the user to consult a healthcare professional.
5. If information comes from web sources, acknowledge this and cite the sources.

Response:"""

        # Tokenize input
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)

        # Generate response
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=512,
                temperature=0.7,
                top_p=0.9,
                do_sample=True
            )

        # Decode response
        response = self.tokenizer.decode(outputs[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True)

        return response.strip(), used_web_search

    def query(self, user_query: str, top_k: int = 5, use_web_search: bool = True) -> str:
        """
        End-to-end RAG pipeline: retrieve + (optional web search) + generate

        Args:
            user_query: User question
            top_k: Number of documents to retrieve
            use_web_search: Whether to use web search when local DB is insufficient

        Returns:
            Generated response
        """
        # First retrieve from local knowledge base
        local_docs = self.retrieve(user_query, top_k=top_k)

        # Check if we need web search
        need_web_search = use_web_search and (
            len(local_docs) == 0 or
            (max([doc['score'] for doc in local_docs], default=0) < self.confidence_threshold)
        )

        combined_docs = local_docs

        # If needed, perform web search
        if need_web_search:
            print("Local knowledge insufficient, performing web search...")
            web_docs = self.search_web(user_query, num_results=3)
            combined_docs = local_docs + web_docs

        # Generate response
        response, used_web = self.generate_response(user_query, combined_docs)

        # Add a note if web search was used
        if used_web:
            response += "\n\n[Note: This response includes information retrieved from web searches.]"

        return response


# Example usage
def main():
    # Initialize RAG system
    # Add your search API key if you have one
    rag = HealthcareRAG(device="cuda", search_api_key=None)

    # Load dataset and build index
    rag.load_healthcare_magic_dataset(limit=10000)
    rag.build_index()

    # Interactive chat loop
    print("\nHealthcare Chatbot Ready! (Type 'exit' to quit)")
    print("This system uses both a local healthcare knowledge base and web search")
    print("=" * 50)

    while True:
        user_input = input("\nYour health question: ")
        if user_input.lower() in ['exit', 'quit', 'q']:
            break

        # Get response with automatic fallback to web search
        response = rag.query(user_input, use_web_search=True)
        print("\nChatbot:", response)
        print("\n" + "-" * 50)


if __name__ == "__main__":
    main()