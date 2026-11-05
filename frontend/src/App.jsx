import React from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';

const pages = {
    '/': 'first.html',
    '/first': 'first.html',
    '/login': 'loginpage.html',
    '/register': 'register.html',
    '/forgot-password': 'forgetlogin.html',
    '/student': 'student.html',
    '/teacher': 'teacher-dashboard.html',
    '/attendance': 'att-pre.html',
    '/marks': 'mark-pre.html',
    '/career': 'career.html',
    '/student-recommendations': 'std-rec.html',
    '/student-profile': 'student-profile.html'
};

const publicRoutes = ['/', '/first', '/login', '/register', '/forgot-password'];

function OriginalPage() {
    const location = useLocation();
    const file = pages[location.pathname] || pages['/'];
    return <iframe title="StudentPath AI page" src={`/pages/${file}`} style={{ width: '100%', height: '100vh', border: 'none' }} />;
}

export default function App() {
    const location = useLocation();

    // Headless check: look for the token saved by your HTML form
    const token = localStorage.getItem('keycloak_token');
    const isAuthenticated = !!token;

    if (location.pathname === '/logout') {
        localStorage.removeItem('keycloak_token');
        return <Navigate to="/login" replace />;
    }

    const isPublic = publicRoutes.includes(location.pathname);

    // Kick unauthenticated users attempting to access private routes back to your custom login
    if (!isAuthenticated && !isPublic) {
        return <Navigate to="/login" replace />;
    }

    // Prevent logged-in users from seeing the login page again
    if (isAuthenticated && location.pathname === '/login') {
        return <Navigate to="/student" replace />;
    }

    return (
        <Routes>
            <Route path="*" element={<OriginalPage />} />
        </Routes>
    );
}