import React from "react";
import {BrowserRouter, Routes, Route, Navigate} from "react-router-dom";
import {Layout} from "./widgets/layout";
import {HomePage} from "./pages/home";
import {ProductsPage} from "./pages/products";
import {AddProductPage} from "./pages/products/AddProductPage";
import {EditProductPage} from "./pages/products/EditProductPage";
import {ProjectsPage} from "./pages/projects";
import {AddProjectPage} from "./pages/projects/AddProjectPage";
import {EditProjectPage} from "./pages/projects/EditProjectPage";
import {ChatsPage} from "./pages/chats";
import {BotsPage} from "./pages/bots";
import {WorkspaceUsersPage} from "./pages/workspace";
import {InvitePage} from "./pages/invites";
import {AvitoAdsPage, AvitoListingsPage} from "./pages/avito";
import {ManualMassPostingPage} from "./pages/manualMassPosting";
import {
    AdBatchesPage,
    AdCreativesPage,
    EditAdCreativePage,
    EditAdPublicationPage,
    AdPublicationsPage,
} from "./pages/ads";
// src/App.tsx
import {Outlet} from "react-router-dom";
import {ProtectedRoute} from "./routes/ProtectedRoute";
import {GuestRoute} from "./routes/GuestRoute";
import {AuthLayout} from "./pages/auth/AuthLayout";
import {LoginPage} from "./pages/auth/LoginPage";
import {RegisterPage} from "./pages/auth/RegisterPage";


const ProtectedLayout: React.FC = () => (
    <ProtectedRoute>
        <Layout>
            <Outlet/>
        </Layout>
    </ProtectedRoute>
);

const App: React.FC = () => {
    return (
        <BrowserRouter>
            <Routes>
                <Route path="/invites/:token" element={<InvitePage/>}/>

                <Route
                    path="/login"
                    element={
                        <GuestRoute>
                            <AuthLayout>
                                <LoginPage/>
                            </AuthLayout>
                        </GuestRoute>
                    }
                />

                <Route
                    path="/register"
                    element={
                        <GuestRoute>
                            <AuthLayout>
                                <RegisterPage/>
                            </AuthLayout>
                        </GuestRoute>
                    }
                />

                <Route element={<ProtectedLayout/>}>

                    <Route path="/" element={<HomePage/>}/>
                    <Route path="/home" element={<Navigate to="/" replace/>}/>
                    <Route path="/products" element={<ProductsPage/>}/>
                    <Route path="/products/add" element={<AddProductPage/>}/>
                    <Route path="/products/:id/edit" element={<EditProductPage/>}/>

                    <Route path="/projects" element={<ProjectsPage/>}/>
                    <Route path="/projects/add" element={<AddProjectPage/>}/>
                    <Route path="/projects/:id/edit" element={<EditProjectPage/>}/>

                    <Route path="/ads" element={<AvitoAdsPage/>}/>
                    <Route path="/ads/publications" element={<AdPublicationsPage/>}/>
                    <Route path="/ads/batches" element={<AdBatchesPage/>}/>
                    <Route path="/ads/creatives" element={<AdCreativesPage/>}/>
                    <Route path="/ads/creatives/:id/edit" element={<EditAdCreativePage/>}/>
                    <Route path="/ads/publications/:id/edit" element={<EditAdPublicationPage/>}/>

                    <Route path="/manual-mass-posting/new" element={<ManualMassPostingPage />} />

                    <Route path="/avito/listings" element={<AvitoListingsPage/>}/>


                    <Route path="/workspace/users" element={<WorkspaceUsersPage/>}/>
                    <Route path="/chats" element={<ChatsPage/>}/>
                    <Route path="/bots" element={<BotsPage/>}/>
                </Route>
            </Routes>
        </BrowserRouter>
    );
};

export default App;
